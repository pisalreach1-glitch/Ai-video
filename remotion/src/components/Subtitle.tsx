import React from "react";
import { useCurrentFrame, useVideoConfig, spring } from "remotion";
import { SubtitleTheme, SubtitleWord } from "../types";
import { loadFont as loadKdam } from "@remotion/google-fonts/KdamThmorPro";
import { loadFont as loadKoulen } from "@remotion/google-fonts/Koulen";
import { loadFont as loadDangrek } from "@remotion/google-fonts/Dangrek";
import { loadFont as loadMoul } from "@remotion/google-fonts/Moul";
import { loadFont as loadKantumruy } from "@remotion/google-fonts/KantumruyPro";

// Pre-load fonts with Remotion Google Fonts loader
const kdamFont = loadKdam("normal", { subsets: ["khmer"] });
const koulenFont = loadKoulen("normal", { subsets: ["khmer"] });
const dangrekFont = loadDangrek("normal", { subsets: ["khmer"] });
const moulFont = loadMoul("normal", { subsets: ["khmer"] });
const kantumruyFont = loadKantumruy("normal", {
  weights: ["700"],
  subsets: ["khmer"],
  ignoreTooManyRequestsWarning: true,
});

interface SubtitleProps {
  text: string;
  theme?: SubtitleTheme;
  customFont?: string;
  index?: number;
  words?: SubtitleWord[];
  subStart?: number;
  subEnd?: number;
  durationSec?: number;
  durationInFrames?: number;
  emoji?: string;
}

export const Subtitle: React.FC<SubtitleProps> = ({
  text,
  theme = "tiktok_viral",
  customFont,
  index = 0,
  words = [],
  subStart = 0,
  subEnd,
  durationSec,
  durationInFrames,
  emoji: customEmoji,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // 1. Snappy pop-in transition with instant 100% opacity (zero fade-in lag)
  const phraseScale = spring({
    frame,
    fps,
    config: {
      damping: 20,
      stiffness: 350,
      mass: 0.35,
    },
    from: 0.96,
    to: 1.0,
  });

  const opacity = 1;

  const cleanText = (text || "").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
  if (!cleanText) {
    return null;
  }

  // 2. Resolve typography & colors based on selected theme
  let fontFamily = kdamFont.fontFamily;
  let textColor = "#FFE500"; // Electric TikTok Gold default
  let stroke = "3.5px #000000";
  let hasBackground = false;
  let bgStyle: React.CSSProperties = {};

  switch (theme) {
    case "capcut_kantumruy":
    case "kantumruy_gold":
      fontFamily = "'KantumruyPro', sans-serif";
      textColor = "#FFE500";
      stroke = "3.5px #000000";
      break;

    case "capcut_battambang":
      fontFamily = "'Battambang', sans-serif";
      textColor = "#00F0FF";
      stroke = "3.5px #000000";
      break;

    case "capcut_fasthand":
      fontFamily = "'Fasthand', cursive";
      textColor = "#FF3399";
      stroke = "3.5px #000000";
      break;

    case "capcut_bokor":
      fontFamily = "'Bokor', display";
      textColor = "#FFAA00";
      stroke = "3.5px #000000";
      break;

    case "capcut_samsung":
      fontFamily = "'SamsungKhmer', sans-serif";
      textColor = "#FFFFFF";
      stroke = "3.5px #000000";
      break;

    case "capcut_siemreap":
      fontFamily = "'Siemreap', sans-serif";
      textColor = "#FFE500";
      stroke = "3.5px #000000";
      break;

    case "capcut_nida":
      fontFamily = "'NiDAAngkor', serif";
      textColor = "#FFD700";
      stroke = "3.5px #000000";
      break;

    case "tiktok_viral":
    case "kdam_viral":
    default:
      fontFamily = kdamFont.fontFamily;
      textColor = "#FFE500";
      stroke = "3.5px #000000";
      break;

    case "comic_tilt":
    case "neon_green":
      fontFamily = dangrekFont.fontFamily;
      textColor = "#00FF66";
      stroke = "3.5px #000000";
      break;

    case "cyber_cyan":
      fontFamily = kdamFont.fontFamily;
      textColor = "#00F0FF";
      stroke = "3.5px #000000";
      break;

    case "cyber_purple":
      fontFamily = kdamFont.fontFamily;
      textColor = "#E879F9";
      stroke = "3.5px #000000";
      break;

    case "frost_diamond":
      fontFamily = koulenFont.fontFamily;
      textColor = "#38BDF8";
      stroke = "3.5px #000000";
      break;

    case "lava_orange":
      fontFamily = dangrekFont.fontFamily;
      textColor = "#FF6B00";
      stroke = "3.5px #000000";
      break;

    case "bubblegum_pink":
      fontFamily = dangrekFont.fontFamily;
      textColor = "#FF3399";
      stroke = "3.5px #000000";
      break;

    case "royal_moul":
    case "moul_impact":
      fontFamily = moulFont.fontFamily;
      textColor = "#FFD700";
      stroke = "3.5px #000000";
      break;

    case "koulen_punch":
    case "koulen_bold":
      fontFamily = koulenFont.fontFamily;
      textColor = "#FF2A54";
      stroke = "3.5px #000000";
      break;

    case "hormozi_white":
      fontFamily = kdamFont.fontFamily;
      textColor = "#FFFFFF";
      stroke = "3.5px #000000";
      break;

    case "hormozi_gold":
      fontFamily = kdamFont.fontFamily;
      textColor = "#FFE500";
      stroke = "3.5px #000000";
      break;

    case "glass_pill":
      fontFamily = kantumruyFont.fontFamily;
      textColor = "#FFE600";
      stroke = "4px #000000";
      hasBackground = true;
      bgStyle = {
        background: "rgba(15, 15, 25, 0.65)",
        backdropFilter: "blur(20px)",
        border: "1.5px solid rgba(255, 255, 255, 0.2)",
        borderRadius: "26px",
        padding: "14px 34px",
        boxShadow: "0 12px 40px rgba(0, 0, 0, 0.7), 0 0 20px rgba(255, 230, 0, 0.15)",
      };
      break;
  }

  // បើមានជ្រើសរើស Font ខ្មែរពិសេសពីបញ្ជី 293 Fonts -> ប្រើប្រាស់ Font នោះភ្លាម
  if (customFont && customFont.trim()) {
    fontFamily = `'${customFont.trim()}', sans-serif`;
  }

  return (
    <div
      style={{
        position: "absolute",
        bottom: "12%", // Lower Third Zone (សមស្របមិនបាំងមុខមនុស្ស)
        left: 0,
        right: 0,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        padding: "0 24px",
        zIndex: 50,
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          transform: `scale(${phraseScale})`,
          opacity,
          maxWidth: "88%",
          textAlign: "center",
          display: "inline-flex",
          flexDirection: "row",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "center",
          gap: "10px",
          ...(hasBackground ? bgStyle : {}),
        }}
      >
        <span
          style={{
            fontFamily,
            fontSize: "48px",
            fontWeight: 900,
            lineHeight: 1.45,
            letterSpacing: "0.5px",
            display: "inline-block",
            wordBreak: "break-word",
            color: textColor,
            WebkitTextStroke: stroke,
            paintOrder: "stroke fill",
            textShadow: "0 4px 16px rgba(0, 0, 0, 0.90), 0 2px 4px rgba(0, 0, 0, 0.85)",
          }}
        >
          {cleanText}
        </span>

        {customEmoji && (
          <span
            style={{
              fontSize: "58px",
              marginLeft: "8px",
              display: "inline-block",
              filter: "drop-shadow(0 4px 10px rgba(0,0,0,0.5))",
            }}
          >
            {customEmoji}
          </span>
        )}
      </div>
    </div>
  );
};
