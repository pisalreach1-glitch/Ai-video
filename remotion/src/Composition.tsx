import {
  Sequence,
  useVideoConfig,
  AbsoluteFill,
  OffthreadVideo,
  staticFile,
  Audio,
  useCurrentFrame,
} from "remotion";
import { CompositionProps, VisualOverlayItem } from "./types";
import { Subtitle } from "./components/Subtitle";
import { ProgressBar } from "./components/ProgressBar";
import { MotionExplainer } from "./components/MotionExplainer";

// 1. Dynamic Video Cut View (Adapts to Split-Screen 50/50, Cinematic B-Roll, or Normal Fullscreen)
const VideoCutView: React.FC<{
  resolvedVideoSrc: string;
  startFromFrame: number;
  endAtFrame: number;
  zoomLevel: number;
  cutStartOnTimeline: number;
  visualOverlays: VisualOverlayItem[];
  fps: number;
}> = ({
  resolvedVideoSrc,
  startFromFrame,
  endAtFrame,
  zoomLevel,
  cutStartOnTimeline,
  visualOverlays,
  fps,
}) => {
  const localFrame = useCurrentFrame();
  const timelineFrame = cutStartOnTimeline + localFrame;

  // Check which overlay is active at this exact timeline frame
  const activeOverlay = (visualOverlays || []).find((ov) => {
    const oStartF = Math.round(ov.start * fps);
    const oDurF = Math.round((ov.end - ov.start) * fps);
    return timelineFrame >= oStartF && timelineFrame < oStartF + oDurF;
  });

  const layout = activeOverlay?.layout || "talking_head";

  // A. Split-Screen (50/50): Speaker takes the BOTTOM 50%
  if (activeOverlay && layout === "split_screen") {
    return (
      <AbsoluteFill style={{ overflow: "hidden", backgroundColor: "#000000" }}>
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            width: "100%",
            height: "50%",
            overflow: "hidden",
            backgroundColor: "#0B0F19",
          }}
        >
          <OffthreadVideo
            src={resolvedVideoSrc}
            startFrom={startFromFrame}
            endAt={endAtFrame}
            style={{
              position: "absolute",
              top: "-25%", // Centers the speaker nicely in the bottom half
              left: 0,
              width: "100%",
              height: "150%",
              objectFit: "cover",
              transform: `scale(${zoomLevel})`,
              transformOrigin: "center center",
            }}
          />
        </div>
      </AbsoluteFill>
    );
  }

  // B. Cinematic Fullscreen B-Roll: Hide video underneath
  if (activeOverlay && (layout === "cinematic_broll" || layout === "real_broll")) {
    return (
      <AbsoluteFill style={{ overflow: "hidden", opacity: 0 }}>
        <OffthreadVideo
          src={resolvedVideoSrc}
          startFrom={startFromFrame}
          endAt={endAtFrame}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </AbsoluteFill>
    );
  }

  // C. Fullscreen Talking Head Video (Normal)
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
      <OffthreadVideo
        src={resolvedVideoSrc}
        startFrom={startFromFrame}
        endAt={endAtFrame}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${zoomLevel})`,
          transformOrigin: "center 32%",
        }}
      />
    </AbsoluteFill>
  );
};

export const ShortComposition: React.FC<CompositionProps> = ({
  videoSrc,
  cuts,
  sfxEvents = [],
  hookTitle = "",
  theme = "tiktok_viral",
  customFont,
  bgm = "lofi",
  visualOverlays = [],
  showProgressBar = true,
}) => {
  const { fps } = useVideoConfig();

  const hasVideo = Boolean(videoSrc && videoSrc.trim());
  const resolvedVideoSrc = hasVideo
    ? videoSrc.startsWith("http://") || videoSrc.startsWith("https://")
      ? videoSrc
      : staticFile(videoSrc)
    : "";

  // Pre-calculate each cut's position on the continuous timeline
  let runningFrames = 0;
  const cutLayouts = cuts.map((cut, cutIndex) => {
    const cutDurationSeconds = Math.max(0.2, cut.end - cut.start);
    const cutDurationFrames = Math.max(1, Math.round(cutDurationSeconds * fps));
    const startFromFrame = Math.max(0, Math.round(cut.start * fps));
    const endAtFrame = startFromFrame + cutDurationFrames;
    const cutStartOnTimeline = runningFrames;
    runningFrames += cutDurationFrames;
    const zoomLevel = cut.zoom ?? (cutIndex % 2 === 1 ? 1.20 : 1.0);

    return {
      cut,
      cutIndex,
      cutDurationSeconds,
      cutDurationFrames,
      startFromFrame,
      endAtFrame,
      cutStartOnTimeline,
      zoomLevel,
    };
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      {/* 1. ស្រទាប់វីដេអូដើម & Smart Cuts (ជាមួយ Auto Split-Screen 50/50 & Dynamic Zoom) */}
      {cutLayouts.map((layout) => (
        <Sequence
          key={`cut-${layout.cutIndex}`}
          from={layout.cutStartOnTimeline}
          durationInFrames={layout.cutDurationFrames}
        >
          <AbsoluteFill style={{ overflow: "hidden" }}>
            {hasVideo ? (
              <VideoCutView
                resolvedVideoSrc={resolvedVideoSrc}
                startFromFrame={layout.startFromFrame}
                endAtFrame={layout.endAtFrame}
                zoomLevel={layout.zoomLevel}
                cutStartOnTimeline={layout.cutStartOnTimeline}
                visualOverlays={visualOverlays}
                fps={fps}
              />
            ) : null}
          </AbsoluteFill>
        </Sequence>
      ))}

      {/* 2. Motion Explainer & B-Roll Overlays (Split-Screen 50/50 & Cinematic B-Roll) */}
      {(visualOverlays || []).map((overlay, oIdx) => {
        const oStartFrame = Math.max(0, Math.round(overlay.start * fps));
        const oDurSec = Math.max(0.5, overlay.end - overlay.start);
        const oDurFrames = Math.max(1, Math.round(oDurSec * fps));

        return (
          <Sequence
            key={`explainer-overlay-${oIdx}`}
            from={oStartFrame}
            durationInFrames={oDurFrames}
          >
            <MotionExplainer
              overlay={overlay}
              durationInFrames={oDurFrames}
            />
          </Sequence>
        );
      })}

      {/* 3. Subtitles Layer (ALWAYS ON TOP of Video and B-Roll, Never Covered!) */}
      {cutLayouts.map((layout) =>
        layout.cut.subtitles.map((sub, subIndex) => {
          // Subtitle Lead Anticipation: 100ms before speech sound for instant mouth sync
          const SUBTITLE_LEAD_SEC = 0.10;
          const subRelStartSec = Math.max(0, sub.start - layout.cut.start - SUBTITLE_LEAD_SEC);
          const subRelEndSec = Math.min(layout.cutDurationSeconds, sub.end - layout.cut.start);
          const subDurationSec = Math.max(0.1, subRelEndSec - subRelStartSec);

          const subStartFrame = layout.cutStartOnTimeline + Math.round(subRelStartSec * fps);
          const subDurationFrames = Math.max(1, Math.round(subDurationSec * fps));

          return (
            <Sequence
              key={`sub-${layout.cutIndex}-${subIndex}`}
              from={subStartFrame}
              durationInFrames={subDurationFrames}
            >
              <Subtitle
                text={sub.text}
                theme={theme}
                customFont={customFont}
                index={layout.cutIndex + subIndex}
                words={sub.words}
                subStart={sub.start}
                subEnd={sub.end}
                durationSec={subDurationSec}
                durationInFrames={subDurationFrames}
                emoji={sub.emoji}
              />
            </Sequence>
          );
        })
      )}

      {/* 4. ស្រទាប់ Sound Effects (Whoosh, Pop, Ding, Cash, Thud) */}
      {(sfxEvents || []).map((sfx, sfxIdx) => {
        const sfxStartFrame = Math.max(0, Math.round(sfx.start * fps));
        const sfxSrc = staticFile(`sfx/${sfx.sound}.wav`);

        return (
          <Sequence
            key={`sfx-${sfxIdx}`}
            from={sfxStartFrame}
            durationInFrames={Math.round(0.6 * fps)}
          >
            <Audio src={sfxSrc} volume={sfx.volume ?? 0.45} />
          </Sequence>
        );
      })}

      {/* 5. ស្រទាប់ Background Music ជាមួយ Smart Audio Ducking */}
      {bgm && bgm !== "none" ? (
        <Audio
          src={staticFile(`music/${bgm}.wav`)}
          loop
          volume={(f) => {
            const currentSec = f / fps;
            let isSpeaking = false;
            let timelineOffset = 0;
            for (const cut of cuts) {
              const cutDur = Math.max(0.2, cut.end - cut.start);
              if (currentSec >= timelineOffset && currentSec <= timelineOffset + cutDur) {
                const relSecInCut = currentSec - timelineOffset;
                for (const sub of cut.subtitles) {
                  const subRelStart = Math.max(0, sub.start - cut.start);
                  const subRelEnd = Math.min(cutDur, sub.end - cut.start);
                  if (relSecInCut >= subRelStart && relSecInCut <= subRelEnd) {
                    isSpeaking = true;
                    break;
                  }
                }
                break;
              }
              timelineOffset += cutDur;
            }
            const targetVol = isSpeaking ? 0.32 : 0.55;
            const fadeIn = Math.min(1, f / 15);
            const totalF = Math.max(1, runningFrames);
            const fadeOut = Math.min(1, Math.max(0, (totalF - f) / 20));
            return Math.max(0, targetVol * fadeIn * fadeOut);
          }}
        />
      ) : null}

      {/* 6. ស្រទាប់ Retention Progress Bar */}
      {showProgressBar && <ProgressBar theme={theme} />}
    </AbsoluteFill>
  );
};
