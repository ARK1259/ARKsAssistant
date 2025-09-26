# ARKsAssistant
Welcome to ARKsAssistant! An assistant written on python using two main softwares, [Vosk](https://github.com/alphacep/vosk-api) and [Pyttsx3](https://github.com/nateshmbhat/pyttsx3).

It was created with a goal: **to allow the user, layback and command their system to do whatever they wish without the need to click a button!**

To achieve this goal many features have been included. This assistant is able to change many of its values using a simple debug menu. It is able to modify its own modules and have other python files, set by the user, as a local module, to use its functions.

Key Features:
- Interchangable Modules
- Modify Voice Recognition Vosk
- Modify Text To Speach Voices Online/Offline
- Use [NaturalVoiceSAPIAdapter](https://github.com/gexgd0419/NaturalVoiceSAPIAdapter)
- Change/Add/Delete Commands
- Use the set of available functions or add your own ones
- Send messages to your Arduino board
- Have different sounds, including startup/shutdown sounds
- Select an option from a list via voice, using the ask_single_entry function
- Useful commands such as: Weather, Crypto, Arduino, Youtube Music API, Media Controls, Keyboard Inputs, Play Audio, Play Video, etc.

### Debug Menu
With the use of [Urwid](https://github.com/urwid/urwid), a simple dubug menu has been made to modify the config.json file for the assistant. Via this menu you are able to change the Behavior, Voices, Vosk, do backup of the modules, Set commands and more. Each section of the debug menu has its own guide, **(WORK IN PROGRESS...)** both simple and complete, to guide fellow programmes or users who are here to enjoy.

## Requirements
### Ignore if:
You are going to download the released version and have no need to learn in detail how the program works.
(The releases have a fully built version of the assistant that requires mostly the things that your Windows already has included.)

### Python
As of 0.02.1V ARKsAssistant has been tested on python 3.13.3 ONLY. In theory it should also work with python 3.13.5 although it has not been tested. Older versions of python might be viable if the dependencies also support them. If you find any issues, know that the assistant will benefit from them in long term, so make sure to report them on the issues.

### Dependencies
The modules or libraries required for the software to function properly are mentioned in the [third party licenses](THIRD-PARTY-LICENSES.md) and the [requirements.txt](requirements.txt).
All Third Party Licenses may also be referenced in these files.

The [install_lib](Install_Lib.bat) file has been included in the repo to fasten the process of installing the requirements. It will update [pip](https://github.com/pypa/pip) and install/update the dependencies mentioned in requirements.txt
This file will ask the user for their opinion on installing [NaturalVoiceSAPIAdapter](https://github.com/gexgd0419/NaturalVoiceSAPIAdapter). For this feature to work, the installer.exe file for NaturalVoiceSAPIAdapter must be located in "./Voiceadaptor/Installer.exe"

### Text to Speech
This program uses Pyttsx3 for text to speech. The use of natural voices is also possible with [NaturalVoiceSAPIAdapter](https://github.com/gexgd0419/NaturalVoiceSAPIAdapter), for installation refer to their respective github repository.
NaturalVoiceSAPIAdapter could be installed via their installer.exe file. This installer file may also be opened/installed via the [install_lib](Install_Lib.bat) file.
Pyttsx3 can be installed using the requirements file.

### Voice Recognition
ARKsAssistant uses [Vosk](https://github.com/alphacep/vosk-api) for voice recognition. Vosk requires a language model provided in their [models](https://alphacephei.com/vosk/models) page. Currently the assistant only supports English models.
To build the assistant without it crashing, you are required to download an English model and include it in "./Code/models/vosken1"
Or as a workaround you may launch [debug_menu.py](Code/debug_menu.py) and use the vosk menu to change its model's location to your model's desired location, and then proceed to using ARKsAssistant.

## Installation
You may Downloaded the latest release,
or build the repository yourself:

#### Option 1: Clone the Repository
If you have **Git** installed, run:
```bash
git clone https://github.com/ARK1259/ARKsAssistant.git
cd ARKsAssistant
```
#### Option 2: Download as ZIP
- Click the Code button on this page.
- Select Download ZIP.
- Extract the ZIP file and open the folder.

In the repository's folder a requirements.txt file is located. you may install the those requirements via:
```
pip install -r requirements.txt
```
or use the [install_lib](Install_Lib.bat) that automatically does that for you.

#### You are now able to use "./Code/debug_menu.py" to adjust your config.json file as you wish!

If you want to use Natural Voices download and install [NaturalVoiceSAPIAdapter](https://github.com/gexgd0419/NaturalVoiceSAPIAdapter) as they instruct you to.
As mentioned before, you can include the installer.exe they provide you in "./Voiceadaptor/Installer.exe" to install it via the install_lib file.

Download an English Vosk model from [models](https://alphacephei.com/vosk/models) and extract it in "./Code/models/vosken1"
It is recommended to use vosk-model-en-us-0.22-lgraph as the model for ARKsAssistant as it is both light and accurate.

#### You are now able to run "./Code/maincode.py" or [Launch.bat](Launch.bat) to run the assistant!

## Guides
Guides have benn included in the repository as well as the wiki on github.
You may access the [guides](Code/guides) in the debug menu of their respective section.

**These files and the wiki are currently under progress and will be finished as soon as possible so stay tuned.**

## A Word from the Developer
Thank you for considering to use ARKsAssistant! This program is made by the one single person that I am in the few spare moments that I have. It is a fully free software, so not only I have yet to gain any profit, I have most likely lost some. You are the only reason for me to keep on working on this project as I myself am quite proud of its current state and see no reason to move forward with it.
Every watch, every star, every follow I get on this repo means a world wants to see a bright future for this assistant. And who am I to deny you that? I have brought this software to this world and I will continue working on it until its purely perfect.

If you want to help me in taking this journey another step forward, Share your ideas and tell me if there is anything you are willing to help with. I have published this program on github in hopes that people will lend their aid in improving it.

Again thank you so much for partaking in the development of ARKsAssistant!

-ARK1259

## Roadmap
- [X] Finish the Readme
- [ ] Publish the release
- [ ] Fix the requirement for vosk model to be in vosken1 folder on first launch with asking the user for its location
- [ ] Clean up the .py files
- [ ] Find Donation methods
