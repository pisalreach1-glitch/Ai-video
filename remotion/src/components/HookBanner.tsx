import React from "react";
import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont as loadKdam } from "@remotion/google-fonts/KdamThmorPro";

const kdamFont = loadKdam("normal", { subsets: ["khmer"] });

interface HookBannerProps {
  title: string;
}

export const HookBanner: React.FC<HookBannerProps> = ({ title }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // បង្ហាញត្រឹម ៣.៥ វិនាទីដំបូងប៉ុណ្ណោះ
  const durationFrames = Math.round(3.5 * fps);
  if (!title || !title.trim() || frame > durationFrames) {
    return null;
  }

  // Slide-down spring pop ពីលើ
  const translateY = spring({
    frame,
    fps,
    config: {
      damping: 10,
      stiffness: 220,
      mass: 0.6,
    },
    from: -120,
    to: 0,
  });

  // Fade-out ស្រទន់នៅ ០.៤ វិនាទីចុងក្រោយ
  const fadeOutStart = durationFrames - Math.round(0.4 * fps);
  const opacity =
    frame < fadeOutStart
      ? 1
      : Math.max(0, 1 - (frame - fadeOutStart) / Math.round(0.4 * fps));

  return (
    <div
      style={{
        position: "absolute",
        top: "12%", // ផ្នែកខាងលើវីដេអូ (ក្រោម notch ទូរស័ព្ទ)
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        padding: "0 24px",
        zIndex: 60,
        opacity,
        transform: `translateY(${translateY}px)`,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          background: "linear-gradient(135deg, rgba(20, 20, 32, 0.92), rgba(10, 10, 20, 0.92))",
          backdropFilter: "blur(20px)",
          border: "2.5px solid rgba(255, 230, 0, 0.65)",
          borderRadius: "36px",
          padding: "14px 40px",
          maxWidth: "92%",
          textAlign: "center",
          boxShadow: "0 16px 45px rgba(0, 0, 0, 0.9), 0 0 30px rgba(255, 230, 0, 0.25)",
        }}
      >
        <span
          style={{
            fontFamily: kdamFont.fontFamily,
            fontSize: "50px",
            fontWeight: 900,
            color: "#FFE600",
            WebkitTextStroke: "4px #000000",
            paintOrder: "stroke fill",
            textShadow: "0 4px 0 #000000, 0 8px 24px rgba(0, 0, 0, 0.9)",
            lineHeight: 1.35,
            letterSpacing: "0.5px",
            wordBreak: "break-word",
            display: "inline-block",
          }}
        >
          {title}
        </span>
      </div>
    </div>
  );
};
