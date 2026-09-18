# Interface direction

A two-pane manager for retrieving flight logs. The flight controller occupies the left half and the computer occupies the right half. The splitter is adjustable and the lists remain side by side. Flight-controller connection and controls stay in the left pane; local navigation stays in the Computer pane. There is no third pane that takes space away from files.

```text
Betaflight Blackbox Desk          Drag logs from the flight controller to your computer
Flight controller                 │ Computer
Device · Search · Connect         │ Back · Up · Path · Choose
Board and storage                 │ Current folder
Log · Recorded · Size             │ Name · Size · Modified
... multi-selection ...           │ ... folders, then logs ...
Copy latest · Copy selected       │ Automatic refresh
Delete · Empty storage · Eject    │ Eject after copying
Shared operation status and progress
```

Palette: paper `#FFFFFF`, flight-controller background `#F1F5FA`, primary text `#172B46`, secondary text `#62738B`, action blue `#245AD1`, error `#B63D49`. The app uses the system font (Helvetica Neue / Segoe UI): 22 for the title, 17 for pane headings, 13 for controls and text. File sizes are right-aligned and file names keep their original capitalization.

In the Computer pane, visible folders always precede files, even in descending order and when sorting by size or date. Only `.bbl` and `.bfl` files are visible, without case sensitivity. The count separates visible folders and logs; other file types remain accessible through Finder or Explorer.

The local selection uses the full row with an explicit light-blue highlight even when focus is elsewhere. **New folder…** creates a subfolder; **Delete…** opens a Trash confirmation. Folder confirmations explicitly include all contents, even items hidden by the Blackbox filter. Local permanent deletion is never used.

The flight-controller list appears as soon as names and sizes are ready. Dates begin as `…` and are updated in the background without changing selection, sort order, or copy status. User operations take precedence over date reads. The status distinguishes waiting for USB storage from listing logs, and About shows the latest connection timings.

A compact blue flight line identifies the app. The rest follows familiar file-manager interaction: click, Shift, and Cmd/Ctrl selection; double-click folders; editable path; Back and Up. The Computer pane turns blue only during a valid drag. Dragging always copies: there is no reverse transfer and no automatic deletion from the flight controller. Filesystem dates are never presented as reliable flight dates.
