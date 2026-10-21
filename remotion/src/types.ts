export type SubtitleTheme =
  | "tiktok_viral"
  | "comic_tilt"
  | "neon_green"
  | "cyber_cyan"
  | "koulen_punch"
  | "hormozi_white"
  | "glass_pill"
  | "kdam_viral"
  | "koulen_bold"
  | "dangrek_vibe"
  | "moul_impact"
  | "kantumruy_gold"
  | "hormozi_gold"
  | "cyber_purple"
  | "frost_diamond"
  | "lava_orange"
  | "bubblegum_pink"
  | "royal_moul"
  | "capcut_kantumruy"
  | "capcut_battambang"
  | "capcut_fasthand"
  | "capcut_bokor"
  | "capcut_samsung"
  | "capcut_siemreap"
  | "capcut_nida";

export interface SubtitleWord {
  text: string;
  start: number;
  end: number;
}

export interface SubtitleItem {
  start: number;
  end: number;
  text: string;
  words?: SubtitleWord[];
  emoji?: string;
  sfx?: string;
}

export interface SmartCut {
  start: number;
  end: number;
  zoom?: number;
  subtitles: SubtitleItem[];
}

export interface SfxEvent {
  start: number;
  sound: string;
  volume?: number;
}

export interface MotionExplainerCard {
  title: string;
  subtitle?: string;
  iconType?: "chart" | "analytics" | "folder" | "table" | "calendar" | "phone" | "database" | "dollar" | "sparkle";
  accentColor?: string;
  rotationDeg?: number;
}

export interface MotionComparisonWidget {
  leftTitle: string;
  leftValues?: number[];
  leftColor?: string;
  rightTitle: string;
  rightValues?: number[];
  rightColor?: string;
}

export interface VisualOverlayItem {
  start: number;
  end: number;
  layout?: "split_screen" | "phone_pip" | "floating_card" | "comparison" | "real_broll" | "polaroid" | "cinematic_broll" | "glass_pill" | "kinetic_stamp" | string;
  canvasTheme?: "dark" | "light";
  stepBadge?: string;
  headlinePrefix?: string;
  highlightWord?: string;
  headlineSuffix?: string;
  floatingIcon?: "chart" | "calendar" | "folder" | "sparkle" | "bulb" | "none";
  cards?: MotionExplainerCard[];
  comparison?: MotionComparisonWidget;
  imageSrc?: string;
  title?: string;
  topic?: string;
  transition?: "spring_pop" | "ken_burns" | "slide_in";
  caption?: string;
  pillText?: string;
  pillCategory?: string;
  accentColor?: string;
  rotationDeg?: number;
}

export interface CompositionProps {
  visualOverlays?: VisualOverlayItem[];
  videoSrc: string;
  cuts: SmartCut[];
  sfxEvents?: SfxEvent[];
  hookTitle?: string;
  fps?: number;
  theme?: SubtitleTheme;
  customFont?: string;
  bgm?: "lofi" | "upbeat" | "hype" | "none" | string;
  showProgressBar?: boolean;
}
