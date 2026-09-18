# Betaflight Blackbox Desk

An offline desktop app for viewing, copying, and managing Blackbox logs from **Betaflight** flight controllers through **USB Mass Storage**. It runs locally on macOS and Windows, with no account, cloud upload, or background service.

The app has two side-by-side panes: the flight controller on the left and a browsable local folder on the right. Drag one or more logs from the flight controller to the computer, or use the copy controls.

## Status

- **Intel Mac:** a standalone `.app` can be built locally and does not require Python or Terminal to run.
- **Windows x64:** the same interface and file-management code are supported. The Windows executable must be built and physically tested on Windows.
- **Flight controllers:** generic Betaflight recognition, with no manufacturer allowlist. Requires MSP 1.44+ (Betaflight 4.3+) and working USB Mass Storage mode.
- The transfer engine has been tested previously on a SpeedyBee F7 V3 with Betaflight 2026.6.1. Other boards and the current UI still require hardware validation.

## Use

1. Start **Betaflight Blackbox Desk**. Connect a disarmed flight controller with a data-capable USB cable and close its connection in Betaflight Configurator.
2. Press **Search**, choose the device, and press **Connect**. The app identifies the flight controller and restarts it into USB Mass Storage mode. You can also select storage already mounted as a USB disk.
3. The left pane lists names and sizes immediately, ordered by the highest log number first. Dates initially displayed as `…` are read in the background; copying and ejection remain available while that happens.
4. Choose a destination in the **Computer** pane. Open subfolders by double-clicking, use Back or Up, or enter a path and press Return. Folders are shown first, followed only by `.bbl` and `.bfl` Blackbox logs.
5. Drag selected logs to the computer pane or onto a displayed subfolder. **Copy latest** and **Copy selected** are also available. Original names and contents are retained. Different name collisions become `_2`, `_3`, and so on; identical existing copies are reused. Every copy is verified with SHA-256, unlocked, and made visible and writable.
6. **Eject flight controller after copying** is enabled by default and also applies to drag-and-drop. Disable it to continue managing files, then use **Eject flight controller** when ready.
7. To delete individual logs, select them and press **Delete selected**. The confirmation dialog lists the files and requires confirmation. The deletion is permanent.

The app never deletes logs automatically after copying, and it does not change PID settings, flight settings, or firmware configuration.

Drag-and-drop works only from **flight controller → computer** and always performs a copy. The flight-controller pane rejects drops; the computer pane does not start drags. Finder, Explorer, and other external drops are ignored. A transfer locks its destination and prevents another operation from overlapping it.

## Ejection and reconnecting

On macOS, **Eject flight controller** safely unmounts all volumes on the validated USB parent disk using `diskutil unmountDisk`, without forcing it. This avoids the immediate remount observed with `diskutil eject` on the SpeedyBee F7 V3.

To use the flight controller again, physically disconnect and reconnect USB, then press **Search** and **Connect**. The app does not keep a persistent blacklist, change macOS automount settings, or run a monitoring process. The disk can still appear in Disk Utility as a physical device with no mounted volume.

Windows requests safe removal through the native Plug and Play API for the physical USB parent of the validated disk; it never forces removal. If Windows refuses, close programs using the flight controller and try again. Physical validation on Windows hardware is still required.

## Managing local files

- **New folder…** creates a subfolder of the current folder. The name must be a valid single folder name; paths and collisions are refused without overwriting anything.
- **Delete…** applies only to the Computer pane. The confirmation shows the selected paths and names. Confirming moves files and folders to the native system Trash. Folders include all their contents, including files hidden by the Blackbox filter.
- Trash uses `QFile.moveToTrash`. If it fails, the app reports the error and never falls back to permanent deletion.
- Local actions are blocked during transfers. The selection is validated again after confirmation and cannot include open flight-controller storage or its folders. Links are moved as links without deleting their targets.

## Deletion and emptying storage

| Betaflight storage exposed | List and copy | Individual deletion | Empty storage |
| --- | --- | --- | --- |
| Writable SDCARD volume, including built-in storage such as SpeedyBee F7 V3 | Yes | Yes, after confirmation | All Blackbox log files, after confirmation |
| FLASH exposed as a virtual filesystem | Yes | No | Full erase over a normal USB connection |
| Read-only SDCARD | Yes | No | Unavailable |

Individual deletion requires validated Blackbox log files. On writable SDCARD, **Empty storage…** includes empty and incomplete Blackbox logs and deletes only numbered `LOG*.BFL` files in the root or `LOGS` folder. It does not format the volume and leaves other files untouched.

For FLASH, the virtual USB disk does not accept deletion. Eject it, disconnect every power source from the flight controller, and reconnect USB only. Press **Search**, choose the flight controller, and press **Empty storage…** before **Connect**. The app reads the board, UID, and FLASH capacity. The final confirmation identifies that exact flight controller and states that its logs will be lost.

Only after confirmation does the app send `MSP_DATAFLASH_ERASE` (72). The flight controller must run Betaflight, use Blackbox FLASH, and be disarmed. The app waits through `MSP_DATAFLASH_SUMMARY` (70) for ready storage with 0 used bytes, for up to 10 minutes. The hardware erase cannot be cancelled after it is sent. An error is never shown as success and does not cause an automatic second erase.

No real erase or deletion is performed by the automated tests.

## Compatibility and limits

- macOS and Windows only. The current Mac build targets **Intel x86_64, macOS 14+**. Apple Silicon needs a dedicated build or Rosetta.
- One flight controller at a time. After a restart, the app looks for one new external USB volume and stops if multiple new volumes appear.
- Selecting an already-mounted disk cannot repeat MSP verification of board and firmware; the UI labels it as storage already connected.
- Flight controllers without MSC are not supported yet; there is no serial fallback for flash downloads.
- Initial supported copy destinations are local APFS/HFS+ volumes on macOS or NTFS on Windows. The conflict-safe publishing procedure uses hard links, so exFAT is unsupported for now.
- Builds are not signed with Apple or Microsoft distribution certificates and are not notarized.

## Development and tests

Python 3.10–3.14 is supported; Python 3.13 is recommended for new Windows builds. Dependencies are pinned in `requirements.txt`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python run_app.py
```

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

Tests use temporary folders and simulated device responses, so they never delete logs from real flight controllers. They cover the Qt interface, copying, collisions, selective deletion, complete emptying, local-file actions, drag direction, and platform adapters.

`run_app.py --demo` starts the interface with temporary sample files only. A yellow banner makes the demo mode explicit and no real device is touched.

## Building an application bundle

```sh
.venv/bin/python tools/build.py
```

The build includes Python, Qt, and dependencies. On macOS it creates `dist/Blackbox Desk.app`; on Windows it creates `dist/Blackbox Desk/Blackbox Desk.exe` and its required dependency folder. Build packages on their destination operating system. Do not copy only the executable out of the Windows folder.

The GitHub Actions workflow in `.github/workflows/build.yml` runs tests and builds on macOS and Windows.

## Publishing a GitHub release

Publish a GitHub Release with a version tag such as `v0.3.5`. The **Build desktop apps** workflow checks out that exact tag and completes the full test suite on macOS before starting independent package builds on an Intel macOS runner and a Windows runner. Each package also passes its executable smoke test. Once both builds succeed, it attaches these ZIP files to the same Release:

- `Blackbox-Desk-macOS-x86_64-vX.Y.Z.zip`, containing the `.app` bundle for Intel Macs.
- `Blackbox-Desk-Windows-x64-vX.Y.Z.zip`, containing the `.exe` and all required files.

The workflow can also be started manually from the Actions tab. Leave the release-tag field blank to build and inspect artifacts without publishing them, or provide the tag of an already published Release to rebuild and update its packages. GitHub-hosted runners produce the packages on their destination operating systems; physical flight-controller validation remains separate.

## Technical sources

- [Betaflight: USB Mass Storage](https://betaflight.com/docs/wiki/guides/current/Mass-Storage-Device-Support)
- [SpeedyBee F7 V3 configuration: built-in SDCARD](https://support.betaflight.com/targets/SPEEDYBEEF7V3)
- [Betaflight flash virtual filesystem](https://github.com/betaflight/betaflight/blob/2026.6.1/src/main/msc/emfat_file.c)
- [Betaflight MSP protocol](https://github.com/betaflight/betaflight/blob/2026.6.1/src/main/msp/msp.c)
- [Qt for Python desktop distribution](https://doc.qt.io/qtforpython-6/faq/distribution.html)
