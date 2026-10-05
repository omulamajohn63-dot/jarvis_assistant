# Jarvis Desktop Voice Assistant🔥

<img src="https://giffiles.alphacoders.com/212/212508.gif" alt="">

**Have you ever wondered how cool it would be to have your own assistant? Imagine how easier it would be doing Wikipedia searches without opening web browsers, and performing many other daily tasks like playing music with the help of a single voice command, opening different browsers in just a voice command.**

**This project is simple desktop voice assistant built with python named as “Jarvis Desktop Voice Assistant”. This project is fully completed and error free. It was compiled in VS Code Editor.**

**🔸 Let's be honest, it's not as intelligent as in the movie, but it can do a lot of cool things and automate your daily tasks you do on your personal computers/laptops.**

## 📌Built with

<code><img height="30" src="https://raw.githubusercontent.com/github/explore/80688e429a7d4ef2fca1e82350fe8e3517d3494d/topics/python/python.png"></code>

## 📌Features

It can do a lot of cool things, some of them being:

- Greet user
- Tell current time and date
- Launch installed applications (say "open Chrome")
- Play songs and videos by name (say "play oh jah")
- Open documents by name, or read them out loud (say "open my cv", "read my cv")
- Answer questions from Wikipedia, no trigger word needed (say "who is einstein")
- Searches every folder of your extra drives, so a flash disk or external HDD works too
- Open folders such as Downloads, Music or Videos, or a whole drive (say "open i:")
- Open any website
- Tells about any person (via Wikipedia)
- Can search anything on Google
- Can take screenshot and save it with custom filename
- Can tell jokes
- Works with your voice **or** the keyboard (type commands instead of speaking)
- Has a browser interface with a transcript, clickable results and a microphone button

## 📌Voice commands

| Say | Jarvis does |
| --- | --- |
| "what is the time" / "what is the date" | tells the time or date |
| "open chrome", "launch notepad", "start task manager" | starts an installed app |
| "play oh jah", "watch apis explained" | plays a song or video from Downloads, Music, Videos, Desktop or Pictures |
| "open my cv", "launch the syllabus pdf" | opens that document in its usual program |
| "read my cv", "read aloud the syllabus" | reads the start of a document out loud |
| "open downloads", "open the music folder" | opens that folder |
| "open youtube", "open google" | opens the website |
| "tell me a joke" | tells a joke |
| "who is einstein", "what is python", "tell me about kenya" | looks it up on Wikipedia and reads it out |
| "mercury" then "2" | picks the second article when a name means several things |
| "screenshot" | saves a screenshot to your Pictures folder |
| "change your name" | renames the assistant |
| "switch to keyboard mode" / "switch to voice mode" | switches how you give commands |
| "be quiet" / "speak up" | stops or resumes speaking replies |
| "shutdown", "restart", "exit" | ends the session (shutdown restarts Windows) |

Matching is forgiving: "open downloada" and "play collo blue top shotta" both work.
If nothing matches well enough, Jarvis says so rather than guessing.

## 🔎 Asking questions

There is no trigger word. **Anything Jarvis has no command for is treated as a
question and looked up on Wikipedia**, so all of these work:

```
You: who is einstein
You: what is python
You: tell me about kenya
You: how do magnets work
You: mt everest
You: what is the time machine
```

Question wording is stripped before searching, so "who is X" looks up X. Saying
"wikipedia" still works if you prefer to be explicit: "wikipedia python" and
"wiki python" do the same thing.

Jarvis always reads the **article title before the text**, so you always know
what you are hearing:

```
You: what is python
Jarvis: Python (programming language). Python is a high-level, general-purpose
        programming language that emphasizes code readability...
```

### When a name means several things

A word like "mercury" is ambiguous, so Jarvis lists the articles rather than
guessing:

```
You: mercury
Jarvis: mercury could mean several things. They are listed on screen with
        numbers. Which one?

  5 articles could match. Which one?
       1. Mercury (planet)
       2. Mercury (element)
       3. Mercury (mythology)
       4. Mercury (toy manufacturer)
       5. Mercury Communications

You: 1
Jarvis: Mercury (planet). Mercury is the first planet from the Sun...
```

Say **more** to page through them, or a number to pick one, or **no** to cancel.
This is the same numbered list used for files and songs.

### Notes and limits

- **The clock is not fooled by a topic.** "what is the time" tells the time, but
  "what is the time machine" looks up *The Time Machine*, because a question
  about the clock that mentions anything else is treated as a real question.
- **Wikipedia's ranking is trusted, not its suggestions.** Wikipedia's own
  automatic suggestion answers "einstein" with the wrong person, so what comes
  back is checked against what was asked and searched again if it drifted.
- **A bad suggestion used to break most lookups.** Titles are read with the
  suggestion turned off, because the library otherwise mangles them
  ("Mount Everest" becomes "mount everes") and then reports no such page.
- **Lookups wait at most 10 seconds** and then say Wikipedia could not be
  reached, instead of hanging.
- Wikipedia answers "what is X". It is not a search engine, so a question like
  "who invented python" reads the article on Python rather than answering the
  question directly.
- In the browser interface the article also appears as a card with a link to
  Wikipedia.

### Extra drives, flash disks and external HDDs

Jarvis searches your normal folders first (Downloads, Music, Videos, Desktop,
Pictures). If nothing matches, it then searches every other drive all the way
down, so plugging in a flash disk just works:

```
You: play gospel
Jarvis: 42 match(es) for 'gospel' on I:

  I:  GOSPEL - 22 file(s)
       1. !!!BEST_OF_ROSE_MUHANDO_Vol_1...  (MP3, 64.7 MB)
       2. 23gospel rmh achia yesu  (MP3, 8.0 MB)
       3. A_SWAHILI GOSPEL SONG MIX  (MP3, 102.3 MB)
  ...
You: 3
Jarvis: Playing A_SWAHILI GOSPEL SONG MIX
```

Every match from every drive is listed, grouped by drive and folder and
numbered, so saying a number plays exactly the line that number is on. Notes:

- Results are printed to the terminal in full, but Jarvis only *speaks* the
  count and where most of the files are, since reading 42 titles aloud would
  take minutes. Longer lists print 200 at a time; say **more** for the next page.
- A drive is re-checked every time, so one plugged in mid-session gets indexed
  and one unplugged is dropped. The system drive (C:) is skipped on purpose,
  and so are partitions under 1 GB such as "System Reserved".
- Scanning the drives can take a few seconds the first time, so Jarvis says
  "Searching your other drives..." while it works.

## 📄 Documents

Say the name of a document and Jarvis finds it, the same way it finds a song.
It looks in the same folders as music plus **Documents**, and if nothing there
matches it walks your other drives, so a document on a flash disk is found too.
PDF, Word, Excel, PowerPoint, text, markdown, CSV, log and RTF files are all
recognised.

```
You: open my cv
Jarvis: 2 match(es) for 'my cv' on C:

  C:  Documents - 1 file(s)
       1. Curriculum Vitae  (PDF, 274 KB)

  C:  Downloads - 1 file(s)
       2. CV template  (DOCX, 32 KB)
You: 1
Jarvis: Opening Curriculum Vitae
```

To hear a document instead of opening it, say "read" or "read aloud":

```
You: read the syllabus
Jarvis: Opening part only: UNIT 1 Introduction to office automation...
```

A few things worth knowing:

- Reading stops after the opening of the document, since a whole document can
  run to hundreds of pages and saying all of it would take longer than reading
  it. Jarvis tells you when it has cut the text short.
- Readable formats are PDF, DOCX, XLSX, XLSM, PPTX, TXT, MD, CSV, LOG and RTF.
  The old pre-2007 formats (.doc, .xls, .ppt) have no reader, so Jarvis says so
  and opens the file for you instead.
- "read" does not open a window; "open" does not read anything. Ask for whichever
  you want.
- Word and Excel lock files (`~$...`) are skipped, so a document open in Word
  does not turn up twice.
- If a name matches several documents they are listed and numbered, and **more**
  pages through them, exactly as with songs.
- An "open" request that matches no document is still tried as an app name, so
  "open chrome" keeps opening Chrome.

## 📌Keyboard mode

At startup Jarvis asks whether you want voice or keyboard input. You can also
skip the question:

```bash
python jarvis.py --keyboard   # start straight in keyboard mode
python jarvis.py --voice      # start straight in voice mode
```

In keyboard mode the same commands work, and Jarvis still speaks its replies
unless you tell it to "be quiet".

## 📱 Browser interface

The same assistant, with a browser for a face:

```bash
python webapp.py
```

It prints a local address and opens your browser:

```
Jarvis is listening on http://127.0.0.1:8765
```

What you get:

- **Hold to talk** — press and hold the microphone button, speak, release. The
  level meter shows it is hearing you. Recording stops by itself after 12
  seconds.
- **Replies type themselves out**, with a blinking caret. Click any reply that
  is still typing to see the rest of it at once. Your own words appear
  immediately, and if your system asks for reduced motion the whole reply
  appears at once too.
- **A transcript** of everything said, in the order it happened.
- **Clickable results** — when a name matches several files they appear as
  numbered cards grouped by drive and folder. Click a card instead of saying
  its number.
- **Chips** of common commands to try with one click.
- **Volume and sound** controls for Jarvis's replies, which the page plays
  itself so your PC speakers stay quiet.

Nothing changes about how commands work: the browser interface and the
terminal run the same code, so a command behaves the same in either.

### How the voice parts work

- The browser records 16 kHz mono audio and posts it to the server, which
  hands it straight to the same speech recognition the terminal uses. Your
  `GOOGLE_SPEECH_API_KEY` is honoured here too.
- Replies are rendered to a WAV on the server and played by the page, so you
  hear them through the browser rather than the speakers.
- `http://127.0.0.1` counts as a secure origin, so the microphone works
  without a certificate being installed.

### Safety

- The server **only binds to the loopback address**, and any request that does
  not come from this machine is refused, so your Wi-Fi and the internet cannot
  reach it.
- "shutdown" and "restart" ask for confirmation in the browser first.
- **close** stops the interface without touching Windows. Start it again with
  `python webapp.py`.
- Two browser tabs share one numbered results list, so use one tab.

To use a different port, edit `PORT` at the top of `webapp.py`.

## Requirements

Python 3.13+

Speech recognition needs the `aifc` and `audioop` modules, which were removed from the Python standard library in 3.13 (PEP 594). Installing `SpeechRecognition>=3.12` pulls in the maintained `standard-aifc` and `audioop-lts` backports automatically, so no extra setup is required.

Reading documents aloud uses `pypdf`, `python-docx`, `openpyxl` and
`python-pptx`. They are installed with everything else, and Jarvis starts fine
without them: it just says it cannot read that format.

The browser interface needs `Flask`.

## 📌Installation

1. **Fork The Repository**
   - Click the "Fork" button on the top right corner of the repository page.

2. **Clone The Repository**
   - Clone the forked repository to your local machine:
     ```bash
     git clone <URL>
     cd Jarvis-Desktop-Voice-Assistant
     ```

3.  **Create and Activate a Virtual Environment**
     - Create a virtual environment:
     ```bash
     python -m venv .venv
     ```
   - Activate the virtual environment:
     - For Windows:
       ```bash
       .venv\Scripts\activate
       ```
     - For macOS/Linux:
       ```bash
       source .venv/bin/activate
       ```
   - This activates the virtual environment and should look like `(venv) directory/of/your/project>`

4. **Install Requirements**

   - Install all the requirements given in **[requirements.txt](https://github.com/kishanrajput23/Jarvis-Desktop-Voice-Assistant/blob/main/requirements.txt)** by running the command `pip install -r requirements.txt`
   - This also installs PyAudio, which is required to access the microphone. On Windows it is installed from a pre-built wheel, so no Visual C++ build tools are needed.

5. **(Optional) Use your own speech API key**

   - Speech recognition uses the public Google Speech API key bundled with SpeechRecognition, which Google may revoke at any time. To use your own key, set the environment variable before starting the assistant:
     ```bash
     set GOOGLE_SPEECH_API_KEY=your-key-here
     ```

6. **Run the Assistant**
  - Run the main script:
    ```bash
    python jarvis.py
    ```
  - Now Enjoy with your own assistant !!!!

7. **Deactivate the Virtual Environment**
   - After you're done, deactivate the virtual environment:
     ```bash
     deactivate
     ```

## 📌Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## 📌Author

👤 **Kishan Kumar Rai**

- Twitter: [@kishan_rajput23](https://twitter.com/kishan_rajput23)
- Github: [@kishanrajput23](https://github.com/kishanrajput23)
- LinkedIn: [@kishan-kumar-rai](https://linkedin.com/in/kishan-kumar-rai-23112000)

## 📌Show your support

Please ⭐️ this repository if this project helped you!

## 📌License

This project is [MIT](https://choosealicense.com/licenses/mit/) licensed.

## 📌Learning Resources to Extend This Project

To build this project further and enhance its capabilities, a strong understanding of the following areas is recommended:

### 🐍 Python Fundamentals
Python is the core language behind this project. A solid grasp of syntax, control flow, functions, and error handling will help you modify and extend the assistant’s functionality.  
👉 [Python Programming Course](https://www.mygreatlearning.com/academy/premium/master-python-programming)

### 🎙️ Voice Processing & NLP
Voice commands are processed using speech and text-based techniques. Understanding Natural Language Processing (NLP) concepts such as tokenization and text analysis can help improve voice interaction.  
👉 [Introduction to NLP](https://www.mygreatlearning.com/academy/learn-for-free/courses/introduction-to-natural-language-processing)

### 🤖 Intelligence & Generative AI
Currently, the assistant follows predefined logic. By integrating Generative AI concepts, it can be enhanced into a conversational assistant capable of generating intelligent responses and performing web-based tasks.  
👉 [Introduction to Generative AI](https://www.mygreatlearning.com/academy/premium/master-generative-ai)

### 👁️ Computer Vision
To make the assistant more advanced, computer vision can be introduced for features like face detection and gesture control. Learning image and video processing fundamentals is a good starting point.  
👉 [Computer Vision Essentials](https://www.mygreatlearning.com/academy/learn-for-free/courses/computer-vision-essentials)

### 📄 Related Reading
For a conceptual overview of building voice assistants in Python, you can refer to this article: [CLICK HERE](https://www.mygreatlearning.com/blog/jarvis-desktop-assistant-python-project/)

---

> *Some learning resources mentioned above are shared as part of an educational collaboration.*
