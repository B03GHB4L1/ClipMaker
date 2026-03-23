================================================================
  CLIPMAKER 1.1 — Setup Guide
  Football highlight reel generator by B4L1
================================================================

WHAT YOU NEED
----------------------------------------------------------------
Before using ClipMaker you need:

  1. Python (free) — the engine that runs everything
  2. A match video file (.mp4) — or two files if split by half
  3. A match event CSV file


STEP 1 — INSTALL PYTHON (one time only)
----------------------------------------------------------------
If you have never used Python before, you need to install it
once. After that, you never need to think about it again.

  Windows:
    1. Go to https://www.python.org/downloads
    2. Click the big yellow "Download Python" button
    3. Run the installer
    4. IMPORTANT: On the first screen, check the box that says
       "Add Python to PATH" — easy to miss, very important
    5. Click Install Now and wait for it to finish

  Mac:
    1. Go to https://www.python.org/downloads
    2. Click the big yellow "Download Python" button
    3. Open the downloaded .pkg file
    4. Follow the installer steps (just keep clicking Continue)


STEP 2 — SET UP THE APP FILES
----------------------------------------------------------------
You should have received a zip folder. Here is what to do:

  Windows:
    1. Unzip the folder you received
    2. Move the entire folder wherever you like on your computer
       (Desktop, Documents, etc.)
    3. That is it — everything is already in the right place

  Mac:
    1. Unzip the folder you received
    2. Inside, you will find a file called ClipMaker.app.zip
       — unzip this too. It will produce ClipMaker.app
    3. Make sure ClipMaker.app sits in the same folder as
       app_streamlit.py (it should already be, just confirm)
    4. IMPORTANT: Move the entire folder to your Desktop or
       Documents BEFORE opening the app. Do not open it
       directly from your Downloads folder — Mac will run it
       from a temporary location and it will not work.


STEP 3 — LAUNCH THE APP
----------------------------------------------------------------
  Windows:
    Double-click Launch_ClipMaker.bat
    A black window will appear — this is normal, leave it open.
    Your browser will open automatically with the app.

  Mac:
    Double-click ClipMaker.app
    The first time, Mac may warn you it is from an unidentified
    developer. Right-click the app → Open → Open to proceed.
    This warning only appears once.
    A Terminal window will appear — leave it open.
    Your browser will open automatically with the app.

The launcher automatically installs everything else it needs
(streamlit, moviepy, pandas). The first launch may take a
minute or two while these download. Every launch after that
will be fast.


USING THE APP
----------------------------------------------------------------
  1. Click Browse next to Video File and select your match video
  2. Click Browse next to CSV File and select your event data
  3. Enter kick-off timestamps (see Kick-off Timestamps below)
  4. Set your period column name (usually "period") or use the
     fallback row index if your CSV has no period column
  5. Apply any action filters if needed (see Filters below)
  6. Adjust clip settings if needed (Before/After buffers,
     Merge Gap)
  7. Choose an output folder and whether you want individual
     clips or one combined reel
  8. Tick Dry Run first to preview the clip list without
     rendering — recommended before committing to a full render
  9. Click Run ClipMaker


KICK-OFF TIMESTAMPS
----------------------------------------------------------------
You need to tell the app exactly when kick-off happens in the
video, so it can match event times to video positions.

  Single video file:
    Enter the timestamps exactly as shown in your video player
    for both halves. For example, if the 1st half kick-off is
    4 minutes 16 seconds into the video, enter: 4:16
    For longer videos use HH:MM:SS format, e.g. 1:00:32

  Two separate video files (split by half):
    Tick "Match is split into two separate video files" at the
    top of the Files section. A second Browse button will appear
    for the 2nd half video.

    IMPORTANT: With two files, each timestamp is relative to
    the start of its own file — not the full match. So if the
    2nd half kick-off is 45 seconds into the second file,
    enter 0:45 for the 2nd Half kick-off. The two files are
    completely independent of each other.


ACTION FILTERS
----------------------------------------------------------------
All filters are optional. Leave them blank to include every
action in the CSV.

  Action Types to Include
    A dropdown list of all action types found in your CSV.
    Select one or more to clip only those types (e.g. only
    Pass and Carry). Leave empty to include all types.

  Progressive actions only
    When ticked, only includes actions where the prog_pass
    or prog_carry value is greater than zero. Requires those
    columns to be present in your CSV.

  Min xT value
    Only clips actions at or above this xT threshold. Set to
    0 to include all. Requires an xT column in your CSV.

  Top N actions by xT
    Ranks all actions by xT (highest first) and clips only
    the top N. For example, set to 10 to get a reel of the
    10 most dangerous moments in the match. Set to 0 to
    include all. Requires an xT column in your CSV.

  Note: Filters stack in order. If you combine multiple filters
  (e.g. Progressive only + Top N by xT), each one is applied
  on top of the previous. Use one at a time if unsure.


PROGRESS AND RENDERING
----------------------------------------------------------------
When you click Run, a progress bar appears below the button.

  During clip cutting:
    Shows "Clip X of Y — Xm XXs remaining"

  During final assembly (combined reel only):
    Shows "Assembling — frame X of Y — Xm XXs remaining"
    When encoding is nearly complete the bar will read:
    "Finalising — merging audio and video, almost done..."
    The bar may appear stuck at this point for a minute or two.
    This is normal — do not close the window. It will finish.


STOPPING THE APP
----------------------------------------------------------------
Close the Terminal or command window that opened when you
launched the app. This stops Streamlit. You can also press
Ctrl+C in that window.


TROUBLESHOOTING
----------------------------------------------------------------
"Python is not installed"
  → Follow Step 1 above.

"Add Python to PATH" was not checked during install (Windows)
  → Uninstall Python and reinstall, checking that box.

"SETUP REQUIRED" message on Mac
  → The app is being run from the wrong location. Move the
     entire ClipMaker folder to your Desktop or Documents,
     then open the app from there.

Browse buttons do not open a file picker (Mac)
  → tkinter is missing. Open Terminal and run:
       brew install python-tk
     If brew is not installed, visit https://brew.sh first.

The app opens but immediately closes
  → Make sure app_streamlit.py is in the same folder as the
     launcher file.

Video file not found error
  → Use the Browse button rather than typing the path manually
     to avoid any issues with spaces or special characters.

Filters show as greyed out
  → The relevant columns (xT, prog_pass, prog_carry) are not
     present in your CSV. Load your CSV file first — the
     filters will activate automatically if the columns exist.

================================================================
  CLIPMAKER 1.1 by B4L1  |  @B03GHB4L1
================================================================
