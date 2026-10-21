import React from "react";
import {
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  Img,
} from "remotion";
import { VisualOverlayItem } from "../types";

interface MotionExplainerProps {
  overlay: VisualOverlayItem;
  durationInFrames: number;
}

// ==========================================
// LAYOUT 1: SPLIT-SCREEN (50/50)
// Top 50%: B-Roll Photo with Ken Burns
// Divider Bar: 6px Glowing Neon Accent
// Bottom 50%: Speaker (Handled by Composition.tsx)
// Pure clean visual without overlay text badges
// ==========================================
const SplitScreenTopView: React.FC<{
  imageSrc: string;
  topic?: string;
  caption?: string;
  accentColor?: string;
  frame: number;
  durationInFrames: number;
  fps: number;
}> = ({
  imageSrc,
  accentColor = "#FFE600",
  frame,
  durationInFrames,
  fps,
}) => {
  const exitOpacity = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const kenBurnsScale = interpolate(
    frame,
    [0, durationInFrames],
    [1.04, 1.14],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const resolvedImg = imageSrc.startsWith("http") ? imageSrc : staticFile(imageSrc);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: 1080,
        height: 960,
        overflow: "hidden",
        backgroundColor: "#0A0D14",
        opacity: exitOpacity,
      }}
    >
      {/* Top 50% Photo with Ken Burns */}
      {imageSrc ? (
        <Img
          src={resolvedImg}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${kenBurnsScale})`,
            transformOrigin: "center center",
          }}
        />
      ) : (
        <div
          style={{
            width: "100%",
            height: "100%",
            background: "radial-gradient(circle at center, #1E293B 0%, #0F172A 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span style={{ fontSize: 90 }}>🎬</span>
        </div>
      )}

      {/* Subtle vignette and bottom dark gradient to blend into divider */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          background:
            "linear-gradient(to bottom, rgba(0,0,0,0.2) 0%, rgba(0,0,0,0) 40%, rgba(0,0,0,0.5) 100%)",
        }}
      />

      {/* 6px Glowing Neon Divider Bar at Boundary (Y = 954) */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          width: "100%",
          height: 6,
          background: `linear-gradient(90deg, #FF6B00 0%, ${accentColor} 50%, #FF6B00 100%)`,
          boxShadow: `0 0 24px ${accentColor}, 0 0 10px #FFFFFF`,
          zIndex: 10,
        }}
      />
    </div>
  );
};

// ==========================================
// LAYOUT 2: CINEMATIC FULLSCREEN B-ROLL
// Fullscreen 1080x1920 Photo Cutaway with Ken Burns
// Pure clean cinema visual without any overlay text badges
// ==========================================
const CinematicBrollView: React.FC<{
  imageSrc: string;
  topic?: string;
  caption?: string;
  pillCategory?: string;
  accentColor?: string;
  floatingIcon?: string;
  frame: number;
  durationInFrames: number;
  fps: number;
}> = ({
  imageSrc,
  frame,
  durationInFrames,
}) => {
  const fadeIn = interpolate(frame, [0, 8], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fadeOut = interpolate(
    frame,
    [durationInFrames - 10, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const kenBurns = interpolate(
    frame,
    [0, durationInFrames],
    [1.0, 1.12],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const resolvedImg = imageSrc.startsWith("http") ? imageSrc : staticFile(imageSrc);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        width: 1080,
        height: 1920,
        overflow: "hidden",
        backgroundColor: "#0A0D14",
        opacity: fadeIn * fadeOut,
      }}
    >
      {/* 1. Fullscreen B-Roll Photo */}
      {imageSrc ? (
        <Img
          src={resolvedImg}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${kenBurns})`,
            transformOrigin: "center center",
          }}
        />
      ) : (
        <div
          style={{
            width: "100%",
            height: "100%",
            background: "radial-gradient(circle at center, #1E293B 0%, #0F172A 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span style={{ fontSize: 120 }}>🎬</span>
        </div>
      )}

      {/* Cinematic Vignette */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          background:
            "radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 100%)",
        }}
      />
    </div>
  );
};

// ==========================================
// MAIN COMPONENT: 3 CLEAN LAYOUTS ONLY
// 1. split_screen (50/50: Top B-Roll, Bottom Speaker)
// 2. cinematic_broll (Fullscreen B-Roll)
// 3. talking_head (Fullscreen Normal Video, returns null)
// ==========================================
export const MotionExplainer: React.FC<MotionExplainerProps> = ({
  overlay,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const layout = overlay.layout || "split_screen";

  // Talking Head = Speaker video pure fullscreen (No overlay)
  if (layout === "talking_head") {
    return null;
  }

  // Cinematic B-Roll = Fullscreen B-Roll Photo Cutaway
  if (layout === "cinematic_broll" || layout === "real_broll") {
    return (
      <CinematicBrollView
        imageSrc={overlay.imageSrc || ""}
        topic={overlay.topic || ""}
        caption={overlay.caption}
        pillCategory={overlay.pillCategory || "🎬 B-ROLL"}
        accentColor={overlay.accentColor || "#FFE600"}
        floatingIcon={overlay.floatingIcon || "sparkle"}
        frame={frame}
        durationInFrames={durationInFrames}
        fps={fps}
      />
    );
  }

  // Split-Screen (50/50) = Default for visual moments
  return (
    <SplitScreenTopView
      imageSrc={overlay.imageSrc || ""}
      topic={overlay.topic || ""}
      caption={overlay.caption}
      accentColor={overlay.accentColor || "#FFE600"}
      frame={frame}
      durationInFrames={durationInFrames}
      fps={fps}
    />
  );
};
