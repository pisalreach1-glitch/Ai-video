# Business Content Workshop

Editable Remotion project: vertical 720 × 1280 video, original audio, and 11 Khmer marketing callouts timed to the supplied transcript.

## Preview and edit

Install Node.js (22 or newer) and Python 3. Download or clone this repository, including `khmer-motion-project.zip` at the repository root. Then run:

```sh
cd business-content-workshop
python3 prepare-assets.py
npm install
npm run dev
```

On Windows, use `python prepare-assets.py` if `python3` is unavailable.

Open the URL printed by Remotion and select **BusinessContentWorkshop**. Edit overlay text and timing in `src/Root.tsx`; see `OVERLAY-PLAN.md` for the cue list. **BusinessContentWorkshopTitle** is a separate title-card composition.

The setup script extracts the original source footage and Khmer fonts from the existing archive. No large media is duplicated. The overlays summarize selected transcript moments; they are not full subtitles. Original audio is preserved and no sound effects have been added.

## Checks

```sh
npx tsc --noEmit
```

TypeScript passed in the authoring workspace. Studio could not be previewed there because its server startup was restricted.
