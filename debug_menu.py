# debug_menu.py

from __future__ import annotations

# --- Standard Library ---
import os
import shutil
import subprocess
import sys
import json
import traceback
import typing
from tkinter import Tk, filedialog
from datetime import datetime

# --- Third-Party Libraries ---
import pyttsx3
import sounddevice as sd
import urwid

# --- Type Checking ---
if typing.TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Iterable

# --- Setup the folder containing maincode.py ---
def main_folder():
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller exe
        return os.path.dirname(sys.executable)
    else:
        # Running as normal Python script
        return os.path.dirname(os.path.abspath(__file__))

# Prepend folder to sys.path BEFORE imports
_main_path = main_folder()
sys.path.insert(0, _main_path)

# --- Local Modules ---
import config_utils

config_dir = config_utils.get_config_path("ARKsAssistant")
config_file = os.path.join(config_dir, "config.json")
commands_file = config_utils.resource_path("commands.json")
action_file = config_utils.resource_path("action_configuration.py")
guides_dir = config_utils.resource_path("guides")

files_to_backup = [commands_file, action_file]

log_lines = urwid.SimpleFocusListWalker([])
log_box = urwid.ListBox(log_lines)

def print(msg: str) -> None:
    # Ensure the message is treated as plain text
    safe_text = str(msg)
    log_lines.append(urwid.Text((None, safe_text)))
    # auto-scroll to bottom
    log_box.set_focus(len(log_lines) - 1)

class MenuButton(urwid.Button):
    def __init__(
        self,
        caption: str | tuple[Hashable, str] | list[str | tuple[Hashable, str]],
        callback: Callable[[MenuButton], typing.Any],
    ) -> None:
        super().__init__("", on_press=callback)

        self._w = urwid.AttrMap(
            urwid.SelectableIcon(["  \N{BULLET} ", caption], 2),
            None,  # normal attr
            "selected",  # focus attr
        )

    def mouse_event(self, size, event, button, x, y, focus):
        """
        Override to highlight button on mouse hover.
        """
        if event == "mouse press" or event == "mouse drag":
            # Let urwid handle clicks normally
            return super().mouse_event(size, event, button, x, y, focus)
        elif event == "mouse move":
            # Set focus to this button when hovering
            self._emit("click") if button else None
            self._w.set_focus_map({"": "selected"})
            return True
        return super().mouse_event(size, event, button, x, y, focus)

palette = [
    (None, "light gray", "black"),
    ("heading", "black", "light gray"),
    ("line", "black", "light gray"),
    ("options", "dark gray", "black"),
    ("body", "dark gray", "black"),
    ("menu", "dark gray", "black"),
    ("focus heading", "white", "dark red"),
    ("focus line", "black", "dark red"),
    ("focus options", "black", "light gray"),
    ("focus", "black", "light gray"),
    ("selected", "white", "dark blue"),
]

focus_map = {"heading": "focus heading", "options": "focus options", "line": "focus line"}

class HorizontalBoxes(urwid.Columns):
    def __init__(self):
        super().__init__([], dividechars=1)

    def open_box(self, box: urwid.Widget):
        """Append a new box to the right."""
        if self.contents:
            del self.contents[self.focus_position + 1 :]
        self.contents.append((urwid.AttrMap(box, "options", focus_map), self.options(urwid.GIVEN, 46)))
        self.focus_position = len(self.contents) - 1

    def replace_box(self, box: urwid.Widget, left: bool = False):
        """Replace currently focused box, or the one to its left, and focus it.
        If left=True, also close the last box (so it doesn’t stay open)."""
        if not self.contents:
            return  # nothing to replace

        pos = self.focus_position
        if left and pos > 0:
            pos -= 1
            # Close/remove the last box if it exists
            if len(self.contents) > pos + 1:
                del self.contents[pos + 1]

        # Replace target position
        self.contents[pos] = (
            urwid.AttrMap(box, "options", focus_map),
            self.options(urwid.GIVEN, 46)
        )

        # Focus on the replacement
        self.focus_position = pos

    def replace_specific_box(self, old_box: urwid.Widget, new_box: urwid.Widget):
        """Replace a specific box in place of old_box."""
        for i, (widget, opts) in enumerate(self.contents):
            if getattr(widget, "original_widget", widget) is old_box:
                self.contents[i] = (urwid.AttrMap(new_box, "options", focus_map), self.options(urwid.GIVEN, 46))
                return

top = HorizontalBoxes()

def with_scroll_indicators(listbox: urwid.ListBox) -> urwid.Widget:
    """
    Wrap a ListBox with scroll indicators. Shows '^' if scrollable up,
    'v' if scrollable down.
    """

    def get_top_indicator():
        focus_position = listbox.body.get_focus()[1]
        return "^" if focus_position > 0 else " "

    def get_bottom_indicator():
        focus_position = listbox.body.get_focus()[1]
        return "v" if focus_position < len(listbox.body) - 1 else " "

    top_text = urwid.Text(get_top_indicator(), align="center")
    bottom_text = urwid.Text(get_bottom_indicator(), align="center")

    frame = urwid.Frame(
        header=top_text,
        body=listbox,
        footer=bottom_text,
    )

    def refresh_indicator(loop=None, user_data=None):
        top_text.set_text(get_top_indicator())
        bottom_text.set_text(get_bottom_indicator())

    # Hook refresh whenever the listbox changes focus
    urwid.connect_signal(listbox.body, "modified", refresh_indicator)

    return frame

class SubMenu(urwid.WidgetWrap):
    def __init__(
        self,
        caption: str | tuple[Hashable, str],
        choices: Iterable[urwid.Widget],
        is_root: bool = False,
        is_backup: bool = False,
    ) -> None:
        super().__init__(MenuButton([caption, "\N{HORIZONTAL ELLIPSIS}"], self.open_menu))
        line = urwid.Divider("\N{LOWER ONE QUARTER BLOCK}")

        # normalize caption into a section name
        section = caption.lower().replace(" ", "_")

        view_button = MenuButton("View", lambda button: top.open_box(view_items(section)))
        guide_button = MenuButton("Guide", lambda button: guide_item(section))
        back_button = MenuButton("Back", go_back)
        exit_button = MenuButton("Exit", exit_program)
        showconfig_button = MenuButton("Show Config Directory", lambda button: os.startfile(config_dir))

        # Backup-related buttons
        getbackup_button = MenuButton("Do Backup", lambda button: backup_files(forced=True))
        rmbackup_button = MenuButton(
            "Delete Backup",
            lambda button: view_action(
                directory=config_utils.resource_path("backup"),
                action=lambda item: delete_directory(config_utils.resource_path(f"backup/{item}")),
            )()  # <-- call the returned opener
        )

        resbackup_button = MenuButton(
            "Restore Backup",
            lambda button: view_action(
                directory=config_utils.resource_path("backup"),
                action=lambda item: restore_backup(config_utils.resource_path(f"backup/{item}")),
            )()  # <-- same fix here
        )


        # Base widgets
        widgets = [
            urwid.AttrMap(urwid.Text(["\n  ", caption]), "heading"),
            urwid.AttrMap(line, "line"),
            urwid.Divider(),
            *choices,
            urwid.Divider(),
        ]

        # Add backup buttons only if requested
        if is_backup:
            widgets.append(getbackup_button)
            widgets.append(rmbackup_button)
            widgets.append(resbackup_button)
            widgets.append(urwid.Divider())

        # Add guide button
        widgets.append(guide_button)

        # Add menu-specific buttons
        if not is_root:
            widgets.append(view_button)
            widgets.append(back_button)
            widgets.append(urwid.Divider())
        else:
            widgets.append(showconfig_button)
            widgets.append(exit_button)
            widgets.append(urwid.Divider())

        listbox = urwid.ListBox(urwid.SimpleFocusListWalker(widgets))

        # Wrap the listbox to handle Esc / Backspace
        class ListBoxWrapper(urwid.WidgetWrap):
            def keypress(self, size, key):
                if key in ("esc", "backspace"):
                    go_back()
                    return None
                return super().keypress(size, key)

        self.menu = urwid.AttrMap(ListBoxWrapper(listbox), "options")

    def open_menu(self, button: MenuButton) -> None:
        top.open_box(self.menu)

class Choice(urwid.WidgetWrap):
    def __init__(
        self,
        caption: str | tuple[Hashable, str] | list[str | tuple[Hashable, str]],
        on_select: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(MenuButton(caption, self.item_chosen))
        self.caption = caption
        self.on_select = on_select

    def item_chosen(self, button: MenuButton) -> None:
        if self.on_select:
            # Run custom action (like opening an input popup)
            self.on_select()
        else:
            # Default behavior: show "You chose …"
            response = urwid.Text(["  You chose ", self.caption, "\n"])
            done = MenuButton("Ok", go_back)
            response_box = urwid.Filler(urwid.Pile([response, done]))
            top.open_box(urwid.AttrMap(response_box, "options"))

def go_back(button: urwid.Widget = None) -> None:
    if len(top.contents) > 1:
        # Remove the current box
        del top.contents[-1]
        # Focus the previous one
        top.focus_position = len(top.contents) - 1

def exit_program(key):
    """Exit Urwid and terminate the Python program completely."""
    raise urwid.ExitMainLoop()  # stop Urwid loop first
    sys.exit(0)                 # exit the Python process

def edit_commands_menu(selected_command=None, selected_prompt=None, selected_function=None):
    def on_checkbox_change(widget, state):
        print(f"{widget.get_label()} is now {state} for {selected_command}")
        section = (widget.get_label().lower()+"_commands")
        edit_commands(key=selected_command, section=section, signal=state)

    def select_command(item):
        key, value = item
        function = edit_commands(key, read=True)
        print(f"Command: {key} |  Prompt: {value}")
        top.replace_box(edit_commands_menu(selected_command=key, selected_prompt=value, selected_function=function), left=True)

    def wrap_widget(widget, focus_map="selected"):
        return urwid.AttrMap(widget, None, focus_map=focus_map)

    widgets = []

    if selected_command:
        title = selected_command.title()
    else:
        title = "Commands"

    # Heading: red background, two lines
    widgets.append(urwid.AttrMap(urwid.Text(["\n  ", f"Editing {title}"]), "heading"))
    # widgets.append(urwid.AttrMap(urwid.Text(" "), "heading"))  # extends heading background

    # Divider line
    widgets.append(urwid.AttrMap(urwid.Divider("\N{LOWER ONE QUARTER BLOCK}"), "line"))  # line divider

    # Add some spacing before main buttons
    widgets.append(urwid.AttrMap(urwid.Divider(), "options"))  # spacing divider

    # Main buttons
    btn_select = wrap_widget(MenuButton("Select Command", view_action("commands", lambda item: select_command(item))))
    if not selected_command:
        widgets.append(urwid.AttrMap(btn_select, None, focus_map="focus"))

    # Only show details if a command is selected
    if selected_command:
        check_online = wrap_widget(urwid.CheckBox(
            "Online",
            state=edit_commands(selected_command, "online_commands"),
            on_state_change=on_checkbox_change
        ))
        check_sensitive = wrap_widget(urwid.CheckBox(
            "Sensitive",
            state=edit_commands(selected_command, "sensitive_commands"),
            on_state_change=on_checkbox_change
        ))
        check_notify = wrap_widget(urwid.CheckBox(
            "Notify",
            state=edit_commands(selected_command, "notify_commands"),
            on_state_change=on_checkbox_change
        ))

        btn_prompt = MenuButton("Add/Change Prompt", lambda button: input_popup(
            "New Prompt",
            pre_text=selected_prompt,
            callback=lambda val: edit_commands(key=selected_command, prompt=val),
            value_type="str"
        ))
        btn_function = MenuButton("Add/Change Function", lambda button: input_popup(
            "Enter New Function",
            pre_text=selected_function,
            callback=lambda val: edit_commands(key=selected_command, function=val),
            value_type="str"
        ))
        btn_import = MenuButton("Import .py as Function", lambda button: input_popup(
            "import Py file",
            callback=lambda key, val: edit_commands(key=selected_command, py_path=val, function=key),
            value_type="str",
            path=True,
            exe_filter=[("Python Files", "*.py")],
            ask_function=True,
            ask_key=False
        ))

        widgets.extend([
            wrap_widget(check_online),
            wrap_widget(check_sensitive),
            wrap_widget(check_notify),
            urwid.AttrMap(urwid.Divider(), "options"),
            wrap_widget(btn_prompt),
            wrap_widget(btn_function),
            wrap_widget(btn_import),
            urwid.AttrMap(urwid.Divider(), "options"),
        ])

    if selected_command:
        btn_select = wrap_widget(MenuButton("Select Another Command", view_action("commands", lambda item: select_command(item))))
        widgets.append(urwid.AttrMap(btn_select, None, focus_map="focus"))

    widgets.append(urwid.AttrMap(urwid.Divider(), "options"))  # spacing divider
    widgets.append(urwid.AttrMap(MenuButton("Back", go_back), None, focus_map="selected"))


    # Use the same SubMenu-like wrapper: ListBox + AttrMap
    listbox = urwid.ListBox(urwid.SimpleFocusListWalker(widgets))

    class ListBoxWrapper(urwid.WidgetWrap):
        def __init__(self, listbox):
            super().__init__(listbox)
            self.listbox = listbox

        def keypress(self, size, key):
            if key in ("esc", "backspace"):
                go_back()
                return None
            return self.listbox.keypress(size, key)

        def render(self, size, focus=False):
            return self.listbox.render(size, focus)

        def rows(self, size, focus=False):
            return self.listbox.rows(size, focus)

    return urwid.AttrMap(ListBoxWrapper(listbox), "options")

def make_on_click(on_select, refresh, value):
    def callback(button):
        if on_select:
            on_select(button, value)
        if refresh:
            refresh()
    return callback

def view_action(section: str = None, action: Callable[[typing.Any], None] = None, directory: str = None):
    """
    Opens a section menu and refreshes in-place after an action.
    """
    def opener(button=None):
        # Nonlocal allows us to update the menu_box reference after refresh
        menu_box: urwid.Widget = None

        def refresh_view():
            nonlocal menu_box
            new_menu = view_items(section, on_select=item_action, directory=directory)
            top.replace_specific_box(menu_box, new_menu)
            menu_box = new_menu  # update reference for future refreshes

        def item_action(btn, item):
            action(item)
            refresh_view()

        # First open
        menu_box = view_items(section, on_select=item_action, directory=directory)
        top.open_box(menu_box)

    return opener

def view_items(
    section: str = None, 
    on_select=None, 
    group_type: str | None = None,
    refresh: Callable[[], None] | None = None,
    directory: str = None,
):
    """
    Return a urwid.ListBox displaying items in a config section
    or folder names in a directory (if provided).
    Supports lists, dicts, or single values.
    Always adds a Back button.
    """
    body = []

    if section == "backup":
        directory = config_utils.resource_path("backup")

    if directory:
        # List only folders in the given directory
        try:
            items = [d for d in os.listdir(directory) if os.path.isdir(os.path.join(directory, d))]
            for idx, folder in enumerate(items, start=1):
                button = urwid.Button(f"{idx}. {folder}")
                if on_select:
                    urwid.connect_signal(
                        button, "click",
                        lambda btn, f=folder: (on_select(btn, f), refresh() if refresh else None)
                    )
                body.append(urwid.AttrMap(button, "options", focus_map))
            if not items:
                body.append(urwid.Text(f"No folders found in {directory}."))
        except Exception as e:
            body.append(urwid.Text(f"Error: {e}"))

    else:
        # Load from config
        if section == "commands":
            config = load_commands()
        else:
            config = load_config()

        data = config.get(section, [])

        # Auto-detect type
        if group_type is None:
            if isinstance(data, dict):
                group_type = "dict"
            elif isinstance(data, list):
                group_type = "list"
            else:
                group_type = "single"

        if group_type == "list":
            for idx, item in enumerate(data, start=1):
                button = urwid.Button(f"{idx}. {item}")
                if on_select:
                    urwid.connect_signal(
                        button, "click",
                        lambda btn, i=item: (on_select(btn, i), refresh() if refresh else None)
                    )
                body.append(urwid.AttrMap(button, "options", focus_map))
            if not data:
                body.append(urwid.Text(f"No {section} entries found."))

        elif group_type == "dict":
            for key, val in data.items():
                label = key if section == "commands" else f"{key}: {val}"
                button = urwid.Button(label)
                if on_select:
                    urwid.connect_signal(
                        button, "click",
                        lambda btn, k=key, v=val: (on_select(btn, (k, v)), refresh() if refresh else None)
                    )
                body.append(urwid.AttrMap(button, "options", focus_map))
            if not data:
                body.append(urwid.Text(f"No {section} entries found."))

        else:
            body.append(urwid.Text(str(data) if data else f"No {section} entries found."))

    # Back button
    body.append(urwid.Divider())
    body.append(MenuButton("Back", go_back))

    # Wrap listbox to handle Esc / Backspace
    class BackHandlingListBox(urwid.ListBox):
        def keypress(self, size, key):
            if key in ("esc", "backspace"):
                go_back()
                return None
            return super().keypress(size, key)

    listbox = BackHandlingListBox(urwid.SimpleFocusListWalker(body))

    return with_scroll_indicators(listbox)

def load_config():
    try:
        return config_utils.load_config()
    except FileNotFoundError:
        return {}  # Default empty if not exists
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def save_config(data):
    try:
        config_utils.save_config(data)
    except Exception as e:
        print(f"Error saving config: {e}")

def add_item(value, section: str, key: str | None = None, group_type: str = "dict"):
    """
    Add or update a value in the config.

    - group_type: 'dict' or 'list'
    - If group_type=='dict', sets config[section][key] = value
      (key must be provided)
    - If group_type=='list', appends value to the list (no duplicates)
      (key is ignored)
    """
    config = load_config()

    # Ensure section exists
    if section not in config:
        config[section] = {} if group_type == "dict" else []

    # Normalize value: store all scalars as strings
    if isinstance(value, (bool, int, float)):
        value = str(value)

    if group_type == "dict":
        if key is None:
            raise ValueError("Key must be provided for dict type sections.")
        config[section][key] = value
        print(f"Set '{key}' in '{section}' to '{value}'.")
    elif group_type == "list":
        if not isinstance(config[section], list):
            config[section] = []

        # Normalize for uniqueness check
        value_str = str(value).strip()
        existing_values = [str(v).strip() for v in config[section]]

        if value_str not in existing_values:
            config[section].append(value)
            print(f"Added '{value}' to '{section}'.")
        else:
            print(f"'{value}' already exists in '{section}'.")
    else:
        raise ValueError("Unsupported group_type. Use 'list' or 'dict'.")

    save_config(config)

def delete_item(selected, section: str, parent_path: str | None = None) -> bool:
    """
    Delete an item or key from the config.

    selected:
      - For lists: the actual item value
      - For dicts: a (key, value) tuple OR just the key
    Returns True if something was deleted, False otherwise.
    """
    if section == "commands":
        load = load_commands()
        save = save_commands
    else:
        load = load_config()
        save = save_config

    # Find the dict that *contains* `section`
    data = load.get(section, {})
    
    # Auto-detect type
    if isinstance(data, dict):
        group_type = "dict"
    elif isinstance(data, list):
        group_type = "list"
    else:
        group_type = "single"

    if group_type == "list":
        if selected in data:
            data.remove(selected)
            save(load)
            print(f"Deleted '{selected}' from {section}.")
            return True
        else:
            print(f"Item '{selected}' not found in {section}.")
            return False

    elif group_type == "dict":
        key_to_delete = selected[0] if isinstance(selected, tuple) else selected
        if key_to_delete in data:
            del data[key_to_delete]
            save(load)
            print(f"Deleted '{key_to_delete}' from {section}.")
            return True
        else:
            print(f"Key '{key_to_delete}' not found in {section}.")
            return False

    else:
        print(f"Unsupported or missing structure for section '{section}'.")
        return False

def load_commands():
    path = config_utils.resource_path("commands.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "commands": {},
            "sensitive_commands": {},
            "online_commands": {},
            "notify_commands": {}
            }

def save_commands(data):
    path = config_utils.resource_path("commands.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def edit_commands(
    key: str = None,
    section: str = None,
    signal: bool = None,
    prompt: str = None,
    function: str = None,
    py_path: str = None,
    read: bool = None,
):

    # For my developers out there, sorry this is a bit of a puzzle right now. I might fix it :)

    data = load_config()

    if py_path:
        # Copy file into resource path
        resources_dir = config_utils.resource_path("")
        os.makedirs(resources_dir, exist_ok=True)
        dest_file = os.path.join(resources_dir, os.path.basename(py_path))

        copy_succeeded = False
        try:
            # Only copy if source and destination are different
            if os.path.abspath(py_path) != os.path.abspath(dest_file):
                shutil.copy2(py_path, dest_file)
                copy_succeeded = True
                print(f"✅ Copied {py_path} → {dest_file}")
            else:
                print(f"ℹ️ File already in resources folder: {dest_file}")
                copy_succeeded = True  # Treat "already there" as success
        except PermissionError:
            print(f"⚠️ Could not copy {py_path} — file is in use by another process.")
        except Exception as e:
            print(f"❌ Error copying {py_path}: {e}")

        # Only add import if copy succeeded
        if copy_succeeded:
            # Derive module name from file (remove .py)
            module_name = os.path.splitext(os.path.basename(py_path))[0]

            # Add import to action_configuration.py if not already present
            with open(action_file, "r", encoding="utf-8") as f:
                content = f.read()

            import_line = f"import {module_name}"
            if import_line not in content:
                with open(action_file, "r+", encoding="utf-8") as f:
                    lines = f.readlines()
                    # Insert import after existing imports (or at top if none)
                    insert_idx = 0
                    for i, line in enumerate(lines):
                        if line.strip().startswith("import") or line.strip().startswith("from"):
                            insert_idx = i + 1
                    lines.insert(insert_idx, import_line + "\n")
                    f.seek(0)
                    f.writelines(lines)
                print(f"✅ Added import: {import_line}")

    if py_path and not copy_succeeded:
        return

    # --- Handle function read/write ---
    if function or read:
        with open(action_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if key:
            # Search for the elif block
            start_index = None
            end_index = None
            for i, line in enumerate(lines):
                if line.strip().startswith(f'elif command == "{key}"'):
                    start_index = i
                    break

            if start_index is not None:
                if read:
                    # Find where the block ends
                    for j in range(start_index + 1, len(lines)):
                        stripped = lines[j].lstrip()
                        if stripped.startswith(("elif", "else")) and not lines[j].startswith(" " * 8):
                            end_index = j
                            break
                    if end_index is None:
                        end_index = len(lines)

                    # Return only the body, skipping the first line
                    return "".join(lines[start_index + 1:end_index])

                # Writing a function: replace next indented line(s)
                if function:
                    indent = " " * 8
                    # Remove existing indented lines after elif
                    block_end = start_index + 1
                    while block_end < len(lines) and lines[block_end].startswith(indent):
                        block_end += 1
                    # Insert new function line
                    lines[start_index + 1:block_end] = [indent + function + "\n"]
            else:
                # If function is provided but key block not found, append new block
                if function:
                    new_block = f'    elif command == "{key}":\n        {function}\n'
                    lines.append("\n")
                    lines.append(new_block)

            # Write back changes if function was modified
            if function:
                with open(action_file, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                data["system"]["lib_changed"] = "True"
                save_config(data)
                print(f"Assigned function for '{key}' in action_configuration.py")

    # --- Handle prompt ---
    data = load_commands()
    if prompt:
        data["commands"][key] = prompt if prompt else None
        save_commands(data)

    # --- Handle signals ---
    if key and section:
        if signal is True:
            data[section][key] = True
            save_commands(data)
            return True
        elif signal is False:
            data[section].pop(key, None)
            save_commands(data)
            return False
        elif signal is None:  # read mode for keys
            return key in data.get(section, {})

def delete_directory(path: str, silent: bool = False) -> bool:
    """
    Delete a directory and all its contents.
    Returns True if deleted successfully, False otherwise.
    """
    if not os.path.exists(path):
        if not silent:
            print(f"Directory does not exist: {path}")
        return False

    if not os.path.isdir(path):
        if not silent:
            print(f"Path is not a directory: {path}")
        return False

    try:
        shutil.rmtree(path)
        if not silent:
            print(f"Deleted directory: {path}")
        return True
    except Exception as e:
        if not silent:
            print(f"Error deleting {path}: {e}")
        return False

def backup_files(silent: bool = False, forced: bool = False):
    """
    Back up files into a dated folder inside /backup/.
    Keeps at most 10 automated backups by deleting the oldest ones.
    User-forced backups are prefixed with 'user_backup_' and are not counted in the 10 limit.
    """
    backup_root = config_utils.resource_path("backup")
    os.makedirs(backup_root, exist_ok=True)

    # List only automated backup directories (ignore user_backup)
    existing_backups = [
        d for d in os.listdir(backup_root)
        if os.path.isdir(os.path.join(backup_root, d)) and not d.startswith("user_backup_")
    ]

    # Sort backups by creation/modification time (oldest first)
    existing_backups.sort(key=lambda d: os.path.getmtime(os.path.join(backup_root, d)))

    # Delete oldest automated backups if more than 9 exist
    while len(existing_backups) >= 10:
        oldest = existing_backups.pop(0)
        path_to_delete = os.path.join(backup_root, oldest)
        delete_directory(path_to_delete, silent)
        if not silent:
            print(f"🗑️ Deleted oldest backup: {oldest}")

    # Create new dated backup folder
    date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = f"user_backup_{date_str}" if forced else date_str
    backup_dir = os.path.join(backup_root, folder_name)
    os.makedirs(backup_dir, exist_ok=True)

    # Copy files
    for file_path in files_to_backup:
        if os.path.isfile(file_path):
            shutil.copy2(file_path, backup_dir)
            if not silent:
                print(f"✅ Copied file {file_path} → {backup_dir}")
        else:
            if not silent:
                print(f"⚠️ File not found: {file_path}")

    return True

def restore_backup(path: str):
    """
    Restore files from a dated backup folder back into resource_path("").
    Example: restore_backup("2025-09-03")
    """
    resource_dir = config_utils.resource_path("")

    if not os.path.exists(path):
        print(f"Backup folder not found: {path}")
        return False

    try:
        for item in os.listdir(path):
            src = os.path.join(path, item)
            dst = os.path.join(resource_dir, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            elif os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
        print(f"Restored backup {path} → {resource_dir}")
        return True
    except Exception as e:
        print(f"Error restoring backup: {e}")
        return False

def guide_item(group_name):
    filename = f"{group_name}_guide.txt"
    guide_path = os.path.join(guides_dir, filename)

    if not os.path.join(guides_dir, filename):
        print(f"No guide found for '{group_name}' at:\n{guide_path}")
        return

    try:
        if sys.platform.startswith("win"):
            os.startfile(guide_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", guide_path])
        else:
            subprocess.run(["xdg-open", guide_path])
        print(f"Opened guide for '{group_name}'.")
    except Exception as e:
        print(f"Failed to open guide: {e}")

def list_tts_voices():
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    for index, voice in enumerate(voices):
        print(f"{index}: {voice.name} - {voice.id}")

def list_audio_devices():
    devices = sd.query_devices()
    print(devices)
    input = sd.default.device[0]
    output = sd.default.device[1]
    print(f"Default Input: {input}")
    print(f"Default Output: {output}")

def input_popup(
    prompt: str = None,
    pre_text: str = None,
    callback = None,
    value_type: str = "str",
    ask_key: bool = True,
    ask_function: bool = False,
    ask_command: bool = False,
    path: bool = False,
    exe_filter=None,
    min_value=None,
    max_value=None
):
    """
    Show a popup asking for input. Calls `callback(value)` after user presses Ok.

    - value_type: 'str', 'int', 'float', 'bool'
    - path: if True, opens a file/folder dialog using Tkinter
    - exe_filter: list of file types for askopenfilename
    """

    # ---- FILE/FOLDER picker mode ----
    if path:
        def handle_value(key: str | None = None):
            root = Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if exe_filter:
                value = filedialog.askopenfilename(
                    title="File location:", filetypes=exe_filter, parent=root
                )
            else:
                value = filedialog.askdirectory(
                    title="Folder Location:", parent=root
                )

            root.destroy()

            if value:
                if key is not None:
                    callback(key.strip(), value)
                elif ask_function:
                    def on_key_entered(key: str):
                        if not key:
                            print("Key cannot be empty.")
                            return
                        callback(key, value)
                    input_popup("Add function name", callback=on_key_entered)
                else:
                    callback(value)
            else:
                print("No file/folder selected.")

        if ask_key:
            def on_key_entered(key: str):
                if not key:
                    print("Key cannot be empty.")
                    return
                handle_value(key)

            input_popup(prompt or "Add entry name", callback=on_key_entered)
            return
        else:
            handle_value()
            return

    # ---- Normal text/bool/int/float input ----
    if value_type == "bool":
        edit = urwid.Edit(f"{prompt} yes/no: ", edit_text=pre_text or "")
    else:
        edit = urwid.Edit(f"{prompt}: ", edit_text=pre_text or "")

    def on_ok(button=None, key: str | None = None):
        try:
            text = edit.get_edit_text().strip()

            if value_type == "int":
                value = int(text)
                if min_value is not None and value < min_value:
                    print(f"Value must be >= {min_value}")
                    return
                if max_value is not None and value > max_value:
                    print(f"Value must be <= {max_value}")
                    return

            elif value_type == "float":
                value = float(text)
                if min_value is not None and value < min_value:
                    print(f"Value must be >= {min_value}")
                    return
                if max_value is not None and value > max_value:
                    print(f"Value must be <= {max_value}")
                    return

            elif value_type == "bool":
                if text.lower() in ["true", "yes", "1"]:
                    value = True
                elif text.lower() in ["false", "no", "0"]:
                    value = False
                else:
                    print("Type 1/0, yes/no, true/false ONLY!")
                    return
            else:
                value = text
            if ask_command:
                def get_prompt(prompt):
                    if prompt is None:
                        return
                    go_back(button)
                    callback(prompt, value)
                go_back(button)
                input_popup("Add Prompt if needed", callback=get_prompt)
            else:
                go_back(button)
                callback(value)

        except ValueError as e:
            print(f"Invalid input: {e}")

    def on_cancel(button=None):
        print("input cancelled!")
        go_back(button)

    orig_keypress = edit.keypress

    def custom_keypress(size, key):
        if key in ("enter", "return"):
            on_ok()
            return None
        elif key == "esc":
            on_cancel()
            return None
        elif key == "ctrl a":
            # Select all
            edit.set_edit_pos(0)
            print("Text selected!")
            edit._overwrite_all = True
            return None
        elif getattr(edit, "_overwrite_all", False):
            if key == "backspace":
                # Clear all text
                edit.set_edit_text("")
                edit.set_edit_pos(0)
                edit._overwrite_all = False
                return None
            elif len(key) == 1:
                # Replace all text with typed character
                edit.set_edit_text(key)
                edit.set_edit_pos(1)
                edit._overwrite_all = False
                return None

        return orig_keypress(size, key)

    edit.keypress = custom_keypress

    ok_btn = MenuButton("Ok", on_ok)
    cancel_btn = MenuButton("Cancel", on_cancel)

    pile = urwid.Pile([
        edit,
        urwid.Divider(),
        urwid.Columns([ok_btn, cancel_btn], dividechars=2),
    ])
    box = urwid.Filler(pile, valign="middle")

    top.open_box(urwid.AttrMap(box, "options"))

group_menus = SubMenu(
    "Debug Menu",
    [
        SubMenu(
            "Audio",
            [
                Choice("Delete", on_select=view_action("audio", lambda item: delete_item(item, "audio"))),
                Choice("List Available Audio Devices", on_select=list_audio_devices),
                Choice("Set Audio Input Device", on_select=lambda: input_popup(
                    "Enter input device ID",
                    pre_text = load_config().get("audio", {}).get("inputdevice", ""),
                    callback=lambda val: add_item(val, "audio", "inputdevice", group_type="dict"),
                    value_type="int"
                )),
                Choice("Set Input Audio Samplerate", on_select=lambda: input_popup(
                    "Enter input samplerate",
                    pre_text = load_config().get("audio", {}).get("inputsamplerate", ""),
                    callback=lambda val: add_item(val, "audio", "inputsamplerate", group_type="dict"),
                    min_value=8000, max_value=44100
                )),
            ],
        ),
        SubMenu(
            "Voices",
            [
                Choice("Delete", on_select=view_action("voices", lambda item: delete_item(item, "voices"))),
                Choice("List Available Voices", on_select=list_tts_voices),
                Choice("Turn Off Speech", on_select=lambda: input_popup(
                    "Turn off assistant speech?",
                    pre_text = load_config().get("voices", {}).get("dontspeak", ""),
                    callback=lambda val: add_item(val, "voices", "dontspeak", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Speech Speed Rate", on_select=lambda: input_popup(
                    "Enter speed rate",
                    pre_text = load_config().get("voices", {}).get("speedrate", ""),
                    callback=lambda val: add_item(val, "voices", "speedrate", group_type="dict"),
                    value_type="int"
                )),
                Choice("Speech Volume Level", on_select=lambda: input_popup(
                    "Enter volume",
                    pre_text = load_config().get("voices", {}).get("volumelevel", ""),
                    callback=lambda val: add_item(val, "voices", "volumelevel", group_type="dict"),
                    value_type="float", min_value=0, max_value=1
                )),
                Choice("Change Online Voice", on_select=lambda: input_popup(
                    "Enter new voice number",
                    pre_text = load_config().get("voices", {}).get("onlinevoice", ""),
                    callback=lambda val: add_item(val, "voices", "onlinevoice", group_type="dict"),
                    value_type="int"
                )),
                Choice("Change Offline Voice", on_select=lambda: input_popup(
                    "Enter new voice number",
                    pre_text = load_config().get("voices", {}).get("offlinevoice", ""),
                    callback=lambda val: add_item(val, "voices", "offlinevoice", group_type="dict"),
                    value_type="int"
                )),
                Choice("Force Online/Offline State", on_select=lambda: input_popup(
                    "Constant offline voice?",
                    pre_text = load_config().get("voices", {}).get("constantofflinevoice", ""),
                    callback=lambda val: add_item(val, "voices", "constantofflinevoice", group_type="dict"),
                    value_type="bool"
                )),
            ],
        ),
        SubMenu(
            "Vosk",
            [
                Choice("Delete", on_select=view_action("vosk", lambda item: delete_item(item, "vosk"))),
                Choice("Logging Level", on_select=lambda: input_popup(
                    "Enter log level value",
                    pre_text = load_config().get("vosk", {}).get("loglevel", ""),
                    callback=lambda val: add_item(val, "vosk", "loglevel", group_type="dict"),
                    value_type="int", min_value=-1, max_value=2
                )),
                Choice("Use Wake Word", on_select=lambda: input_popup(
                    "Use wake word?",
                    pre_text = load_config().get("vosk", {}).get("use_wake_word", ""),
                    callback=lambda val: add_item(val, "vosk", "use_wake_word", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Wake Word Phrase", on_select=lambda: input_popup(
                    "Enter new wake word",
                    pre_text = load_config().get("vosk", {}).get("wake_word", ""),
                    callback=lambda val: add_item(val, "vosk", "wake_word", group_type="dict"),
                    value_type="str"
                )),
                Choice("Wake State Timeout", on_select=lambda: input_popup(
                    "Enter new wake state timeout",
                    pre_text = load_config().get("vosk", {}).get("wake_timeout", ""),
                    callback=lambda val: add_item(val, "vosk", "wake_timeout", group_type="dict"),
                    value_type="int", min_value=3
                )),
                Choice("Follow Dictionary", on_select=lambda: input_popup(
                    "Follow dictionary?",
                    pre_text = load_config().get("vosk", {}).get("dictionary", ""),
                    callback=lambda val: add_item(val, "vosk", "dictionary", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Print All Heard (After Dictionary!)", on_select=lambda: input_popup(
                    "Print all that is heard?",
                    pre_text = load_config().get("vosk", {}).get("printall", ""),
                    callback=lambda val: add_item(val, "vosk", "printall", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Print Heard Phrases in Range", on_select=lambda: input_popup(
                    "Print heard phrases in range?",
                    pre_text = load_config().get("vosk", {}).get("printinput", ""),
                    callback=lambda val: add_item(val, "vosk", "printinput", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Disable Vosk", on_select=lambda: input_popup(
                    "Disable Vosk?",
                    pre_text = load_config().get("vosk", {}).get("disablevosk", ""),
                    callback=lambda val: add_item(val, "vosk", "disablevosk", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Refresh Recognizer", on_select=lambda: input_popup(
                    "Refresh recognizer?",
                    pre_text = load_config().get("vosk", {}).get("refresh", ""),
                    callback=lambda val: add_item(val, "vosk", "refresh", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Recognizer Refresh Rate", on_select=lambda: input_popup(
                    "Enter refresh rate value",
                    pre_text = load_config().get("vosk", {}).get("refreshrate", ""),
                    callback=lambda val: add_item(val, "vosk", "refreshrate", group_type="dict"),
                    value_type="int", min_value=5
                )),
                Choice("Matching Command Strictness", on_select=lambda: input_popup(
                    "Matching strictness",
                    pre_text = load_config().get("vosk", {}).get("strictness", ""),
                    callback=lambda val: add_item(val, "vosk", "strictness", group_type="dict"),
                    value_type="float", min_value=0, max_value=1
                )),
                Choice("Change English Model", on_select=lambda: input_popup(
                    "Enter new model path",
                    callback=lambda val: add_item(val, "vosk", "vosk-en", group_type="dict"),
                    value_type="str", path=True, ask_key=False
                )),
                Choice("Minimum Input Word(s)", on_select=lambda: input_popup(
                    "Min input word",
                    pre_text = load_config().get("vosk", {}).get("minwords", ""),
                    callback=lambda val: add_item(val, "vosk", "minwords", group_type="dict"),
                    value_type="int", min_value=1
                )),
                Choice("Maximum Input Word(s)", on_select=lambda: input_popup(
                    "Max input word",
                    pre_text = load_config().get("vosk", {}).get("maxwords", ""),
                    callback=lambda val: add_item(val, "vosk", "maxwords", group_type="dict"),
                    value_type="int", min_value=2
                )),
            ],
        ),
        SubMenu(
            "Behavior",
            [
                Choice("Delete", on_select=view_action("behavior", lambda item: delete_item(item, "behavior"))),
                Choice("Input for Confirm", on_select=lambda: input_popup(
                    "Enter confirm command",
                    pre_text = load_config().get("behavior", {}).get("confirm", ""),
                    callback=lambda val: add_item(val, "behavior", "confirm", group_type="dict"),
                    value_type="str"
                )),
                Choice("Input for Decline", on_select=lambda: input_popup(
                    "Enter decline command",
                    pre_text = load_config().get("behavior", {}).get("decline", ""),
                    callback=lambda val: add_item(val, "behavior", "decline", group_type="dict"),
                    value_type="str"
                )),
                Choice("Number of Attempts for Confirmation", on_select=lambda: input_popup(
                    "Enter attempt count",
                    pre_text = load_config().get("behavior", {}).get("repeatition", ""),
                    callback=lambda val: add_item(val, "behavior", "repeatition", group_type="dict"),
                    value_type="int", min_value=1
                )),
                Choice("Ask Timeout", on_select=lambda: input_popup(
                    "Enter timeout seconds",
                    pre_text = load_config().get("behavior", {}).get("timeout", ""),
                    callback=lambda val: add_item(val, "behavior", "timeout", group_type="dict"),
                    value_type="int", min_value=1
                )),
                Choice("Print Internet Status on Change", on_select=lambda: input_popup(
                    "Print internet status?",
                    pre_text = load_config().get("behavior", {}).get("printinternet", ""),
                    callback=lambda val: add_item(val, "behavior", "printinternet", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Force Offline Mode", on_select=lambda: input_popup(
                    "Force offline mode?",
                    pre_text = load_config().get("behavior", {}).get("forceofflinemode", ""),
                    callback=lambda val: add_item(val, "behavior", "forceofflinemode", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Command Cooldown", on_select=lambda: input_popup(
                    "Enter new cooldown value",
                    pre_text = load_config().get("behavior", {}).get("command_cooldown", ""),
                    callback=lambda val: add_item(val, "behavior", "command_cooldown", group_type="dict"),
                    value_type="float"
                )),
                Choice("Restart Assistant after Debug", on_select=lambda: input_popup(
                    "Restart assistant after using debug menu?",
                    pre_text = load_config().get("system", {}).get("restart_on_debug", ""),
                    callback=lambda val: add_item(val, "system", "restart_on_debug", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Use an Arduino Board", on_select=lambda: input_popup(
                    "Use Arduino?",
                    pre_text = load_config().get("behavior", {}).get("arduino", ""),
                    callback=lambda val: add_item(val, "behavior", "arduino", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Arduino Port", on_select=lambda: input_popup(
                    "Enter Arduino port",
                    pre_text = load_config().get("behavior", {}).get("arduinoport", ""),
                    callback=lambda val: add_item(val, "behavior", "arduinoport", group_type="dict"),
                    value_type="str"
                )),
            ],
        ),
        SubMenu(
            "System Sounds",
            [
                Choice("Delete", on_select=view_action("sounds", lambda item: delete_item(item, "sounds")
                )),
                Choice("Change Shutdown Sound", on_select=lambda: input_popup(
                    "Choose shutdown mp3",
                    callback=lambda val: add_item(val, "sounds", "shutdown", group_type="dict"),
                    ask_key=False, path=True, exe_filter=[("Audio Files", "*.mp3")]
                )),
                Choice("Change Startup Sound", on_select=lambda: input_popup(
                    "Choose startup mp3",
                    callback=lambda val: add_item(val, "sounds", "startup", group_type="dict"),
                    ask_key=False, path=True, exe_filter=[("Audio Files", "*.mp3")]
                )),
                Choice("Change Notification Sound", on_select=lambda: input_popup(
                    "Choose startup mp3",
                    callback=lambda val: add_item(val, "sounds", "startup", group_type="dict"),
                    ask_key=False, path=True, exe_filter=[("Audio Files", "*.mp3")]
                )),
            ],
        ),
        SubMenu(
            "Add Media",
            [
                Choice("Delete", on_select=view_action("audio", lambda item: delete_item(item, "audio"))),
                Choice("Add Audio File", on_select=lambda: input_popup(
                    "Add the audio name",
                    callback=lambda key, val: add_item(val, section="audio", key=key, group_type="dict"),
                    path=True, exe_filter=[("Audio Files", ("*.mp3", "*.wav", "*.ogg"))]
                )),
                Choice("Add Video File", on_select=lambda: input_popup(
                    "Add the video name",
                    callback=lambda key, val: add_item(val, section="video", key=key, group_type="dict"),
                    path=True, exe_filter=[("Video Files", ("*.mp4", "*.mov", "*.mkv"))]
                )),
            ],
        ),
        SubMenu(
            "LaunchReq",
            [
                Choice("Delete", on_select=view_action("launchreq", lambda item: delete_item(item, "launchreq"))),
                Choice("Print Active Commands on Launch", on_select=lambda: input_popup(
                    "print commands on launch?",
                    pre_text = load_config().get("launchreq", {}).get("printcommands", ""),
                    callback=lambda val: add_item(val, "launchreq", "printcommands", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Perform Welcome Message", on_select=lambda: input_popup(
                    "Do welcome?",
                    pre_text = load_config().get("launchreq", {}).get("dowelcome", ""),
                    callback=lambda val: add_item(val, "launchreq", "dowelcome", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Welcome Message Speech", on_select=lambda: input_popup(
                    "Enter new welcome message",
                    pre_text = load_config().get("launchreq", {}).get("welcomemessage", ""),
                    callback=lambda val: add_item(val, "launchreq", "welcomemessage", group_type="dict"),
                    value_type="str"
                )),
                Choice("Play Startup Audio", on_select=lambda: input_popup(
                    "Play startup sound?",
                    pre_text = load_config().get("launchreq", {}).get("playstartup", ""),
                    callback=lambda val: add_item(val, "launchreq", "playstartup", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Perform Shutdown Message", on_select=lambda: input_popup(
                    "Do shutdown message?",
                    pre_text = load_config().get("launchreq", {}).get("dogoodby", ""),
                    callback=lambda val: add_item(val, "launchreq", "dogoodby", group_type="dict"),
                    value_type="bool"
                )),
                Choice("Shutdown Message", on_select=lambda: input_popup(
                    "Enter new shutdown message",
                    pre_text = load_config().get("launchreq", {}).get("shutdownmessage", ""),
                    callback=lambda val: add_item(val, "launchreq", "shutdownmessage", group_type="dict"),
                    value_type="str"
                )),
                Choice("Play Shutdown Audio", on_select=lambda: input_popup(
                    "Play shutdown sound?",
                    pre_text = load_config().get("launchreq", {}).get("playshutdown", ""),
                    callback=lambda val: add_item(val, "launchreq", "playshutdown", group_type="dict"),
                    value_type="bool"
                )),
            ],
        ),
        SubMenu(
            "Applications",
            [
                Choice("Delete", on_select=view_action("applications", lambda item: delete_item(item, "applications"))),
                Choice("Add", on_select=lambda: input_popup(
                    "Add new application name",
                    callback=lambda key, val: add_item(val, section="applications", key=key, group_type="dict"),
                    path=True, exe_filter=[("Executable files", ["*.exe", "*.msi"])]
                )),
            ],
        ),
        SubMenu(
            "APIs",
            [
                Choice("Delete", on_select=view_action("apis", lambda item: delete_item(item, "apis"))),
                Choice("Add Weather API", on_select=lambda: input_popup(
                    "Add weatherapi.com API key",
                    pre_text = load_config().get("apis", {}).get("weatherapi", ""),
                    callback=lambda val: add_item(val, "apis", "weatherapi", group_type="dict"),
                    value_type="str"
                )),
                Choice("Add Ninjas API", on_select=lambda: input_popup(
                    "Add api-ninjas.com API key",
                    pre_text = load_config().get("apis", {}).get("ninjasapi", ""),
                    callback=lambda val: add_item(val, "apis", "ninjasapi", group_type="dict"),
                    value_type="str"
                )),
            ],
        ),
        SubMenu(
            "Commands",
            [
                Choice("Delete", on_select=view_action("commands", lambda item: delete_item(item, "commands"))),
                Choice("Add", on_select=lambda: input_popup(
                    "New command",
                    callback=lambda prompt, val: (edit_commands(key=val, prompt=prompt, section="commands"),
                    top.open_box(edit_commands_menu(selected_command=val, selected_prompt=prompt)
                )),
                    value_type="str",
                    ask_command=True,
                )),
                Choice("Edit", on_select=lambda: top.open_box
                    (edit_commands_menu()
                )),
            ],
        ),
        SubMenu(
            "City Names",
            [
                Choice("Delete", on_select=view_action("city_names", lambda item: delete_item(item, "city_names"))),
                Choice("Add", on_select=lambda: input_popup(
                    "Enter city name",
                    callback=lambda val: add_item(val, "city_names", group_type="list"),
                    value_type="str"
                )),
            ],
        ),
        SubMenu(
            "Crypto Names",
            [
                Choice("Delete", on_select=view_action("crypto_names", lambda item: delete_item(item, "crypto_names"))),
                Choice("Add", on_select=lambda: input_popup(
                    "Enter crypto name",
                    callback=lambda val: add_item(val, "crypto_names", group_type="list"),
                    value_type="str"
                )),
            ],
        ),
        SubMenu(
            "Backup",
            [
                
            ],
            is_backup=True,
        )
    ],
    is_root=True,
)

top.open_box(group_menus.menu)

layout = urwid.Pile([
    ('weight', 3, urwid.Filler(top, "middle", height=("relative", 80))),  # main menu
    ('weight', 1, urwid.AttrMap(log_box, "options")) # log panel
])

def run_ui():
    backup_files(True)
    try:
        urwid.MainLoop(layout, palette).run()
    except KeyboardInterrupt:
        print("Interrupted by user.")
    except Exception:
        print("Unexpected error:")
        traceback.print_exc()  # prints full traceback with line numbers

if __name__ == "__main__":
    data = load_config()
    if "system" not in data:
        data["system"] = {}
    data["system"]["lib_changed"] = "False"
    save_config(data)
    run_ui()