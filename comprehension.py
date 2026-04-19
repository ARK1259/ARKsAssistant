"""
Input text is sent here for comprehension
What this module feeds back is sent to action_configuration, then to its corresponding action file
"""

# --- Standard Library ---
import re
import random

# --- Local Modules ---
from config_utils import (
    get_config_entry,
    load_commands,
)
from starter import (
    t, 
    lang,
)

# As of 29/03/2026 I am yet to fully comprehend this comprehension module, thus if you wish to grasp
# the true extent of the functions, ask someone else or figure it out yourself.

numbers_dict = t.t("defaults.numbers_dict")

def normalize_number(phrase):
    phrase = phrase.lower().strip()
    
    # pure digits
    if phrase.isdigit():
        return int(phrase)

    words = phrase.split()
    numbers = []

    # convert words to numeric values
    for word in words:
        if word not in numbers_dict:
            numbers.append(None)  # invalid token
        else:
            numbers.append(numbers_dict[word])

    max_number = None
    n = len(numbers)

    # single numbers
    for i in range(n):
        if numbers[i] is not None:
            if max_number is None or numbers[i] > max_number:
                max_number = numbers[i]

    # check all contiguous pairs for valid combination
    for i in range(n - 1):
        a, b = numbers[i], numbers[i + 1]
        if a is None or b is None:
            continue
        # combine if second number < 10 (like "fifty two" -> 50+2)
        if a >= 10 and b < 10:
            combined = a + b
            if max_number is None or combined > max_number:
                max_number = combined

    return max_number

def get_number(text):
    words = text.lower().split()
    i = 0
    max_number = None

    while i < len(words):
        j = i
        candidates = []

        while j < len(words) and (words[j] in numbers_dict or words[j].isdigit()):
            candidates.append(words[j])
            j += 1

        if candidates:
            # ONLY try suffixes (right-aligned)
            for start in range(len(candidates)):
                phrase = " ".join(candidates[start:])
                number = normalize_number(phrase)

                if number is not None:
                    if max_number is None or number > max_number:
                        max_number = number

            i = j
        else:
            i += 1

    return str(max_number) if max_number is not None else ""

def check_required_entities(found_entities, required_entities):
    """
    required_entities:
      [
        ["a", "b"],   # OR
        ["c"]         # AND
      ]
    """
    for group in required_entities:
        if not any(ent in found_entities for ent in group):
            return False
    return True

def resolve_keywords(keyword_def, entity_defs):
    """
    Expands keyword definitions and returns a dict that preserves
    ALL keyword keys and their original values.
    """

    if not isinstance(keyword_def, dict):
        return {}

    result = {}

    source = keyword_def.get("source")
    entity = keyword_def.get("entity")
    additional = keyword_def.get("additional", {})

    # --- Expand entity-based keywords ---
    if source == "entity_values":
        values = (
            entity_defs
            .get(entity, {})
            .get("values", {})
        )

        # Entity values as dict → copy fully
        if isinstance(values, dict):
            for key, value in values.items():
                result[key] = value

        # Entity values as list → key maps to itself
        elif isinstance(values, list):
            for key in values:
                result[key] = key

    # --- Include additional keywords EXACTLY as defined ---
    if isinstance(additional, dict):
        for key, value in additional.items():
            result[key] = value

    return result

def phrase_in_free_span(text, phrase, occupied_spans):
    for match in re.finditer(r'\b' + re.escape(phrase) + r'\b', text, re.IGNORECASE):
        start, end = match.span()

        if all(end <= s or start >= e for s, e in occupied_spans):
            return True, (start, end)

    return False, None

def extract_entities(text, entity_defs):
    text_lower = text.lower()
    found_entities = {}
    occupied_spans = []

    number_from_text = get_number(text_lower)

    for entity_name, entity_info in entity_defs.items():
        matches = []

        # --- Regex-based entities ---
        if entity_info["type"] == "regex":
            target_text = number_from_text if entity_name == "time" else text_lower
            matches = []

            patterns = entity_info.get("patterns", [])
            if not patterns:
                print(t.t("error.patterns_not_found"))
                continue

            # --- Case 1: patterns is a dict (mapping mode) ---
            if isinstance(patterns, dict):
                # iterate over value (the key you want in output) and pattern
                for val, pattern in patterns.items():
                    compiled = re.compile(pattern, re.IGNORECASE)
                    for match in compiled.finditer(target_text):
                        start, end = match.span()

                        # skip if span overlaps with occupied_spans
                        if not all(end <= s or start >= e for s, e in occupied_spans):
                            continue

                        match_text = match.group(0).strip()
                        if match_text:
                            # here we store the dict key as val, and matched text as txt
                            matches.append((val, match_text, start, end))

                if matches:
                    mode = entity_info.get("match_mode", "longest")
                    if mode == "first":
                        val, txt, start, end = matches[0]
                    else:
                        val, txt, start, end = max(matches, key=lambda x: len(x[1]))

                    found_entities[entity_name] = {val: txt}
                    occupied_spans.append((start, end))

            # --- Case 2: patterns is a list (normal mode) ---
            else:
                if entity_name == "number":
                    if number_from_text:
                        found_entities[entity_name] = int(number_from_text)
                else:
                    for pattern in patterns:
                        compiled = re.compile(pattern, re.IGNORECASE)
                        for match in compiled.finditer(target_text):
                            match_text = match.group(0).strip()
                            start, end = match.span()
                            if match_text:
                                matches.append((match_text, start, end, None))

                                matches.sort(key=lambda x: len(x[0]), reverse=True)

                            for txt, start, end, _ in matches:
                                if all(end <= s or start >= e for s, e in occupied_spans):
                                    found_entities[entity_name] = txt
                                    occupied_spans.append((start, end))
                                    break

                    if matches:
                        mode = entity_info.get("match_mode", "longest")
                        if mode == "first":
                            found_entities[entity_name] = matches[0]
                        else:
                            txt, start, end, _ = max(matches, key=lambda x: len(x[0]))
                            found_entities[entity_name] = txt
                            occupied_spans.append((start, end))

        # --- Gazetteer-based entities ---
        if entity_name in found_entities:
            continue
        elif entity_info["type"] == "gazetteer":

            values = entity_info.get("values", {})
            if not values:
                print(t.t("error.values_not_found"))
                continue

            # Case 1: dict-based gazetteer
            if isinstance(values, dict):
                # Refer to elsewhere if specified
                for key, mapped_value in values.items():
                    if key == "READ":
                        type = dict if mapped_value["type"] == "dict" else list
                        values = get_config_entry(mapped_value["section"], value_type=type)
                        continue
                    else:
                        values.update({key: mapped_value})

                for key, mapped_value in values.items():
                    for phrase in [key, mapped_value]:
                        ok, span = phrase_in_free_span(text_lower, phrase, occupied_spans)
                        if ok:
                            matches.append((key, mapped_value, span, None))

                if matches:
                    final_matches = []
                    for match in sorted(matches, key=lambda x: len(x[0]), reverse=True):
                        _, _, (start, end), _ = match
                        if not any(s <= start < e or s < end <= e for _, _, (s, e), _ in final_matches):
                            final_matches.append(match)

                    best_key, best_value, (start, end), _ = max(final_matches, key=lambda x: len(x[0]))
                    found_entities[entity_name] = {best_key: best_value}

            # Case 2: list-based gazetteer
            elif isinstance(values, list):
                for value in values:
                    ok, span = phrase_in_free_span(text_lower, value, occupied_spans)
                    if ok:
                        matches.append((value, span, None, None))

                if matches:
                    value, (start, end), _, _ = max(matches, key=lambda x: len(x[0]))
                    found_entities[entity_name] = value
                    occupied_spans.append((start, end))

    return found_entities

def detect_attributes(intent_definitions, intent):
    attr = intent_definitions.get(intent, {})

    online = bool(attr.get("online", False))
    notify = bool(attr.get("notify", False))

    return {
        "online": online,
        "notify": notify,
    }

def detect_intent(text, intent_defs, entity_defs):
    text_lower = text.lower()
    entities = extract_entities(text, entity_defs)

    best_intent = None
    best_keyword = None
    best_score = 0

    for intent, info in intent_defs.items():

        keywords = resolve_keywords(info.get("keywords", {}), entity_defs)

        keyword_candidates = []

        original_kw = None

        new_kw = None

        translation = None

        # --------------------------------------------------
        # 🔹 First Pass → Detect Matching Keywords
        # --------------------------------------------------
        for kw, kw_info in keywords.items():
            original_kw = kw

            if isinstance(kw_info, dict):
                translation = kw_info.get("translation")

            if translation:
                if isinstance(translation, list):
                    for t in translation:
                        new_kw = t.strip().lower()

                        if not re.search(rf"\b{re.escape(new_kw)}\b", text_lower):
                            continue
                        if kw == new_kw:
                            continue

                        kw = new_kw
                else:
                    kw = translation.strip().lower()

            if not re.search(rf"\b{re.escape(kw)}\b", text_lower):
                continue

            if isinstance(kw_info, dict):
                conditions = kw_info.get("condition", [])
            else:
                conditions = []

            keyword_candidates.append({
                "keyword": kw,
                "original_kw": original_kw,
                "conditions": conditions,
            })

        if not keyword_candidates:
            continue

        # --------------------------------------------------
        # 🔥 Score Keywords Individually
        # --------------------------------------------------
        scored_keywords = []
        kw_with_conditions = []

        for candidate in keyword_candidates:
            kw = candidate["keyword"]
            original_kw = candidate["original_kw"]
            conditions = candidate["conditions"]

            keyword_score = 1  # base score for match

            # Bonus according to matched conditions
            if conditions:
                for c in conditions:
                    length = len(c)
                    if not entities.keys():
                        keyword_score -= 1
                    for k in entities.keys():
                        if k not in (c):
                            keyword_score -= 1
                            continue
                        else:
                            keyword_score += 1
                            length -= 1
                            kw_with_conditions.append(k)
                keyword_score -= length

            else:
                for k in entities.keys():
                    if k:
                        for k in kw_with_conditions:
                            keyword_score -= 0.5
                keyword_score += 2

            # Bonus if keyword length is longer (more specific keyword wins)
            keyword_score += len(kw) * 0.01

            if original_kw:
                kw = original_kw

            scored_keywords.append((kw, conditions, keyword_score))

        # --------------------------------------------------
        # ✅ Pick Best Keyword
        # --------------------------------------------------
        best_local = max(scored_keywords, key=lambda x: x[2])
        chosen_keyword, chosen_condition, local_score = best_local

        # --------------------------------------------------
        # 🔹 Combine Conditions From ALL Matched Keywords
        # --------------------------------------------------

        required = chosen_condition if chosen_condition else info.get(
            "required_entities", []
        )

        # --------------------------------------------------
        # 🔥 Entity Validation Scoring
        # --------------------------------------------------
        final_score = local_score

        if required:
            if check_required_entities(entities, required):
                final_score += 4
            else:
                final_score -= 5

        # --------------------------------------------------
        # ✅ Compare With Global Best Intent
        # --------------------------------------------------
        if final_score > best_score:
            best_score = final_score
            best_intent = intent
            best_keyword = chosen_keyword

    return best_intent, best_keyword

last_prompt = None
def detect_prompt(text, general_prompts, command_info = None, keyword = None): 
    repeat_prompts = get_config_entry(
        "comprehension", "repeat_prompts",
        default=False,
        value_type=bool
    )

    global last_prompt

    if not keyword:
        return None
    
    command_prompts = None
    keyword_prompts = None
    prompts = {}
    new = {}
    silence = False
    use_general = False

    rules = [
        "SILENCE",
        "USE_GENERAL",
        "DISABLE"
    ]

    if command_info:
        additional = command_info["keywords"].get("additional", {})
        keyword_info = additional.get(keyword, {}) if additional else None
        keyword_prompts = keyword_info.get("prompts", {}) if keyword_info else None

        command_prompts = command_info.get("prompts", {})

        if keyword_prompts:
            prompts = keyword_prompts

        elif command_prompts:
            prompts = command_prompts

        if prompts:
            if prompts.get("DISABLE", False):
                return None
            if prompts.get("SILENCE", False):
                silence = True
            if prompts.get("USE_GENERAL", False):
                use_general = True

            if use_general:
                prompts.update(general_prompts)

            for p, c in prompts.items():
                if p in rules:
                    continue
                if p:
                    new.update({p: c})

        if new:
            prompts = new
        else:
            prompts = general_prompts
        
    text = text.lower()

    unconditional_prompts = []
    conditional_prompts = []
    # --- 1️⃣ Check main categories (what, how, can, could)
    for prompt, condition in prompts.items():
        if prompt in rules:
            continue

        if not condition:
            unconditional_prompts.append(prompt)
        else:
            if isinstance(condition, list):
                for w in condition:
                    if re.search(rf"\b{re.escape(w)}\b", text):
                        conditional_prompts.append(prompt)
            else:
                w = condition
                if re.search(rf"\b{re.escape(w)}\b", text):
                    conditional_prompts.append(prompt)

    if conditional_prompts:
        final_prompts = conditional_prompts
    elif unconditional_prompts:
        final_prompts = unconditional_prompts
    else:
        return None
    
    if silence is True:
        final_prompts.append("")

    if not repeat_prompts and last_prompt:
        if final_prompts:
            if last_prompt in final_prompts:
                prompts_count = len(final_prompts)
                if prompts_count > 1:
                    final_prompts.remove(last_prompt)

    random_prompt = random.choice(list(final_prompts))
    last_prompt = random_prompt

    if random_prompt:
        return random_prompt
    else:
        return None

def normalize(text):
    return re.sub(r"[^\w\s]", "", text.lower()).strip()

def split_by_wake_word(text, wake_word):
    """
    Returns (before, after) text around wake word.
    """
    text = normalize(text)
    wake_word = normalize(wake_word)

    pattern = rf"\b{re.escape(wake_word)}\b"
    match = re.search(pattern, text)

    if not match:
        return None, None

    before = text[:match.start()].strip()
    after = text[match.end():].strip()

    return before, after

def is_valid_wake(text, wake_word, intent_defs, entity_defs):
    before, after = split_by_wake_word(text, wake_word)

    if before is None:
        return False

    # Case 1: wake word alone
    if not before and not after:
        return True

    # Case 2: command AFTER wake word
    if after:
        intent = detect_intent(after, intent_defs, entity_defs)
        return intent is not None

    # Case 3: command BEFORE wake word
    if before:
        intent = detect_intent(before, intent_defs, entity_defs)
        return intent is not None

    return False

def confirm_text(text):
    confirm = get_config_entry(
        "phrases", "confirm",
        default=t.t("defaults.confirm"),
        value_type=str
    )
    decline = get_config_entry(
        "phrases",
        "decline",
        default=t.t("defaults.decline"),
        value_type=str
    )

    text_lower = text.lower()
    phrase = None

    for c in [confirm, decline]:
        if not re.search(rf"\b{re.escape(c)}\b", text_lower):
            continue
        else:
            phrase = c

    if not phrase:
        return None

    if phrase == confirm:
        return True
    elif phrase == decline:
        return False

def parse_command(text, activated=False, tcp=False):
    commands = load_commands(lang)

    entity_definitions = commands["ENTITY_DEFINITIONS"]
    intent_definitions = commands["INTENT_DEFINITIONS"]
    general_prompts = commands["GENERAL_PROMPTS"]
    prompt = None

    wake_word = get_config_entry(
        "comprehension", "wake_word",
        default=t.t("defaults.wake_word"),
        value_type=str
    )
    use_wake_word = get_config_entry(
        "comprehension", "use_wake_word",
        default=True,
        value_type=bool
    )
    print_command = get_config_entry(
        "comprehension", "print_command",
        default=False,
        value_type=bool
    )

    if not text:
        return None

    wake_detected = False

    # --- WAKE WORD CHECK ---
    if tcp:
        wake_detected = True
    elif use_wake_word and not activated:
        wake_detected = is_valid_wake(text, wake_word, intent_definitions, entity_definitions)

    # --- COMMAND MODE ---
    entities = extract_entities(text, entity_definitions)
    intent, keyword = detect_intent(text, intent_definitions, entity_definitions)
    attributes = detect_attributes(intent_definitions, intent)
    command_info = None

    if intent:
        command_info = commands["INTENT_DEFINITIONS"][intent]
        prompt = detect_prompt(text, general_prompts, command_info, keyword)

    attributes.update({"prompt": prompt})

    command = {
        "activated": wake_detected,
        "intent": intent,
        "keyword": keyword,
        "entities": entities,
        "attributes": attributes,
    }
    
    if print_command:
        print(command)    

    return command

# --- Test loop ---
# Unhash the section below in order to run the comprehension module and test its output

# while True:
#     user_input = input("You: ")
#     if user_input.lower() in ("exit", "quit"):
#         break

#     result = parse_command(user_input)
#     if not get_config_entry("comprehension", "print_command", default=False, value_type=bool):
#         print(result)