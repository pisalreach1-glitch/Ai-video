import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import { SubtitleTheme } from "../types";

interface ProgressBarProps {
  theme?: SubtitleTheme;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({ theme = "tiktok_viral" }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const progress = Math.min(1, Math.max(0, frame / Math.max(1, durationInFrames - 1)));
  const progressPercent = progress * 100;

  let gradient = "linear-gradient(90deg, #FFE500, #FFB800)";
  let glow = "#FFE500";

  switch (theme) {
    case "tiktok_viral":
    case "kdam_viral":
    case "hormozi_white":
    case "hormozi_gold":
    case "glass_pill":
    default:
      gradient = "linear-gradient(90deg, #FFE500, #FFB800)";
      glow = "#FFE500";
      break;
    case "comic_tilt":
    case "neon_green":
      gradient = "linear-gradient(90deg, #00FF66, #00F0FF)";
      glow = "#00FF66";
      break;
    case "koulen_punch":
    case "koulen_bold":
      gradient = "linear-gradient(90deg, #FF2A54, #FF7A00)";
      glow = "#FF2A54";
      break;
    case "cyber_purple":
      gradient = "linear-gradient(90deg, #C084FC, #E879F9)";
      glow = "#C084FC";
      break;
    case "frost_diamond":
      gradient = "linear-gradient(90deg, #38BDF8, #FFFFFF)";
      glow = "#38BDF8";
      break;
    case "lava_orange":
      gradient = "linear-gradient(90deg, #FF5722, #FF8A00)";
      glow = "#FF5722";
      break;
    case "bubblegum_pink":
      gradient = "linear-gradient(90deg, #FF3399, #FF66B2)";
      glow = "#FF3399";
      break;
    case "cyber_cyan":
      gradient = "linear-gradient(90deg, #00F0FF, #0077FE)";
      glow = "#00F0FF";
      break;
    case "royal_moul":
    case "moul_impact":
      gradient = "linear-gradient(90deg, #FFD700, #FFA500)";
      glow = "#FFD700";
      break;
  }

  return (
    <div
      style={{
        position: "absolute",
        bottom: 0,
        left: 0,
        right: 0,
        height: "8px",
        backgroundColor: "rgba(0, 0, 0, 0.45)",
        zIndex: 100,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          width: `${progressPercent}%`,
          height: "100%",
          background: gradient,
          boxShadow: `0 0 14px ${glow}, 0 0 4px #FFFFFF`,
          borderTopRightRadius: "4px",
          borderBottomRightRadius: "4px",
          transition: "width 0.04s linear",
        }}
      />
    </div>
  );
};
