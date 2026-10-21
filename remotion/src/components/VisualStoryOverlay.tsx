import React from "react";
import {
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  Img,
} from "remotion";
import { VisualOverlayItem } from "../types";

interface VisualStoryOverlayProps {
  overlay: VisualOverlayItem;
  durationInFrames: number;
}

export const VisualStoryOverlay: React.FC<VisualStoryOverlayProps> = ({
  overlay,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 1. Spring Pop Entrance
  const entranceSpring = spring({
    frame,
    fps,
    config: {
      damping: 14,
      stiffness: 210,
      mass: 0.8,
    },
  });

  const entranceOpacity = interpolate(frame, [0, 6], [0, 1], {
    extrapolateRight: "clamp",
  });

  // 2. Smooth Exit (Fade out & subtle sink)
  const exitDuration = Math.min(10, Math.floor(durationInFrames * 0.2));
  const exitStart = Math.max(0, durationInFrames - exitDuration);
  const exitOpacity = interpolate(frame, [exitStart, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const exitScale = interpolate(frame, [exitStart, durationInFrames], [1, 0.94], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // 3. Ken Burns Dynamic Pan & Zoom
  const kenBurnsZoom = interpolate(
    frame,
    [0, durationInFrames],
    [1.0, 1.15],
    { extrapolateRight: "clamp" }
  );
  const kenBurnsPanY = interpolate(
    frame,
    [0, durationInFrames],
    [0, -14],
    { extrapolateRight: "clamp" }
  );

  const totalOpacity = entranceOpacity * exitOpacity;
  const cardScale = entranceSpring * exitScale;

  // Resolve Image Source
  const rawSrc = overlay.imageSrc || "";
  const resolvedSrc =
    rawSrc.startsWith("http://") || rawSrc.startsWith("https://")
      ? rawSrc
      : staticFile(rawSrc);

  return (
    <div
      style={{
        position: "absolute",
        top: "16%",
        left: 0,
        right: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        opacity: totalOpacity,
        transform: `scale(${cardScale})`,
        transformOrigin: "center center",
        pointerEvents: "none",
      }}
    >
      {/* Sleek Floating Card */}
      <div
        style={{
          width: "88%",
          maxWidth: 960,
          height: 520,
          borderRadius: 36,
          overflow: "hidden",
          position: "relative",
          backgroundColor: "rgba(10, 10, 15, 0.85)",
          border: "3px solid rgba(255, 255, 255, 0.35)",
          boxShadow:
            "0 30px 80px rgba(0, 0, 0, 0.9), 0 0 40px rgba(255, 215, 0, 0.28), inset 0 0 20px rgba(255, 255, 255, 0.1)",
        }}
      >
        {/* Animated AI Image with Ken Burns */}
        <div
          style={{
            width: "100%",
            height: "100%",
            transform: `scale(${kenBurnsZoom}) translateY(${kenBurnsPanY}px)`,
            transformOrigin: "center center",
          }}
        >
          <Img
            src={resolvedSrc}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
            }}
          />
        </div>

        {/* Subtle Vignette & Gradient Shading */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background:
              "linear-gradient(to top, rgba(0,0,0,0.6) 0%, transparent 40%, rgba(0,0,0,0.3) 100%)",
            pointerEvents: "none",
          }}
        />

        {/* Topic Pill / Badge */}
        {overlay.topic ? (
          <div
            style={{
              position: "absolute",
              bottom: 22,
              left: 26,
              right: 26,
              backgroundColor: "rgba(0, 0, 0, 0.65)",
              backdropFilter: "blur(12px)",
              padding: "10px 22px",
              borderRadius: 20,
              border: "1.5px solid rgba(255, 215, 0, 0.5)",
              color: "#FFFFFF",
              fontSize: 26,
              fontWeight: 800,
              fontFamily: "sans-serif",
              letterSpacing: "0.03em",
              textShadow: "0 2px 8px rgba(0,0,0,0.8)",
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              width: "fit-content",
            }}
          >
            <span style={{ fontSize: 24 }}>✨</span>
            <span>{overlay.topic}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
};
