import { Config } from "@remotion/cli/config";
import fs from "fs";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer("angle");

const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
if (fs.existsSync(chromePath)) {
  Config.setBrowserExecutable(chromePath);
}
