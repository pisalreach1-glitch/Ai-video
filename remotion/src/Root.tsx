import "./fonts.css";
import React from "react";
import { Composition } from "remotion";
import { ShortComposition } from "./Composition";
import { CompositionProps, SmartCut } from "./types";

const defaultProps: CompositionProps = {
  videoSrc: "",
  cuts: [
    {
      start: 0,
      end: 2,
      subtitles: [{ start: 0, end: 2, text: "សួស្តីបងប្អូនទាំងអស់គ្នា" }],
    },
  ],
  fps: 30,
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ShortComposition"
      // @ts-ignore
      component={ShortComposition}
      durationInFrames={60}
      fps={30}
      width={1080}
      height={1920}
      // @ts-ignore
      defaultProps={defaultProps}
      calculateMetadata={({ props }: any) => {
        const typedProps = props as CompositionProps;
        const fps = typedProps.fps || 30;
        const totalDurationSec = (typedProps.cuts || []).reduce(
          (acc: number, cut: SmartCut) => acc + Math.max(0.2, cut.end - cut.start),
          0
        );
        const durationInFrames = Math.max(1, Math.round(totalDurationSec * fps));

        return {
          durationInFrames,
          fps,
        };
      }}
    />
  );
};
