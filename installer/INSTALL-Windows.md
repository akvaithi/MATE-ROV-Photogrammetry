# Photogrammetry Studio — Windows install

## 1. Install the app

Run **PhotogrammetryStudio-Setup.exe** and follow the wizard (installs per-user,
no admin needed).

> Windows will show a blue **"Windows protected your PC"** box because the app
> isn't code-signed. Click **More info → Run anyway**. (This is expected for a
> small team's unsigned build.)

Launch it from the Start Menu (or the desktop shortcut).

## 2. Install a reconstruction engine (one-time)

The app captures frames and views models on its own, but turning photos into a 3D
model needs one external engine. **RealityScan is the easy choice** (free, best
quality, no special GPU):

1. Download from **[realityscan.com/download](https://www.realityscan.com/download)**
2. Sign in with a free Epic Games account and install it
3. **Launch RealityScan once and sign in** (this activates the free license the
   app relies on)

The app finds it automatically — no configuration.

*Alternative:* Meshroom (open-source) also works, but **only on machines with an
NVIDIA graphics card**.

## 3. Use it

1. **Settings** — set your camera's RTSP URL (or skip if you'll import photos).
2. **Capture** — capture frames from the stream, **or** click **Import Images…**
   to load a folder of photos (great for a quick test — no camera needed).
   Aim for 20–50 overlapping photos of the object from many angles.
3. **Reconstruct** — pick a detail level (**Medium** is a good start; Preview is
   fast but coarse) and press **Start**.
4. When it finishes, click **View in 3D** to rotate the model. The output folder
   also contains `model.glb` (textured), `model.stl` (opens anywhere), and an OBJ.

## Troubleshooting

- **"No reconstruction engine available"** — install RealityScan (step 2) and
  launch it once to sign in.
- **Reconstruction fails / "too few images"** — capture more overlapping photos
  with good lighting; make sure the object fills the frame.
- **A model looks low-poly** — raise the detail level from Preview to Medium/Full.
