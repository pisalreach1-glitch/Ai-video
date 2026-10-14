import {AbsoluteFill, Composition, Interactive, interpolate, useCurrentFrame, useVideoConfig, staticFile, Sequence} from 'remotion';
import './fonts.css';
import {Video} from '@remotion/media';

const BusinessContentWorkshop = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{backgroundColor: '#101923', color: '#f6f3ed', fontFamily: 'Arial, sans-serif', padding: 140, justifyContent: 'center'}}>
      <Interactive.Div name="Workshop label" premountFor={fps} style={{fontSize: 30, letterSpacing: 8, color: '#b7d5bd', marginBottom: 42}}>CONTENT WORKSHOP</Interactive.Div>
      <Interactive.Div name="Workshop title" premountFor={fps} style={{fontSize: 112, fontWeight: 700, lineHeight: 1.08, maxWidth: 1450, opacity: interpolate(frame, [0, fps], [0, 1], {extrapolateRight: 'clamp'})}}>Business Content Workshop</Interactive.Div>
      <Interactive.Div name="Accent line" premountFor={fps} style={{width: 180, height: 8, backgroundColor: '#b7d5bd', marginTop: 60}} />
    </AbsoluteFill>
  );
};

const MarketingOverlay = ({children}: {children: string}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <Interactive.Div name="Marketing text" premountFor={fps} style={{position: 'absolute', left: 54, right: 54, bottom: 92, padding: '28px 30px', borderRadius: 18, borderLeft: '6px solid #b7d5bd', backgroundColor: 'rgba(16,25,35,0.92)', color: '#f6f3ed', fontFamily: 'Noto Sans Khmer, Arial, sans-serif', fontSize: 32, lineHeight: 1.65, fontWeight: 700, whiteSpace: 'pre-line', opacity: interpolate(frame, [0, 0.2 * fps], [0, 1], {extrapolateRight: 'clamp'})}}>{children}</Interactive.Div>;
};

const WorkshopFootage = () => {
  const {fps} = useVideoConfig();
  return <AbsoluteFill style={{backgroundColor: '#101923'}}>
    <Video name="Workshop source footage" src={staticFile('IMG_5777_small.MOV')} durationInFrames={4324} premountFor={fps} style={{width: '100%', height: '100%', objectFit: 'contain'}} />
    <Sequence name="Student feedback" from={Math.round(11.72 * fps)} durationInFrames={Math.round(15.54 * fps) - Math.round(11.72 * fps)} premountFor={fps}>
      <MarketingOverlay>{"មតិយោបល់ពីសិស្សរៀនធ្វើម្ហូប"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Black broth noodles" from={Math.round(19.38 * fps)} durationInFrames={Math.round(23.7 * fps) - Math.round(19.38 * fps)} premountFor={fps}>
      <MarketingOverlay>{"សាកធ្វើគុយទាវទឹកខ្មៅ\nញ៉ាំឆ្ងាញ់គ្រប់គ្នា"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Student video" from={Math.round(32.48 * fps)} durationInFrames={Math.round(38.54 * fps) - Math.round(32.48 * fps)} premountFor={fps}>
      <MarketingOverlay>{"សិស្សផ្ញើវីដេអូជូនអ្នកគ្រូ\nអរគុណសម្រាប់ការចែករំលែក"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Listen to feedback" from={Math.round(41.48 * fps)} durationInFrames={Math.round(45.02 * fps) - Math.round(41.48 * fps)} premountFor={fps}>
      <MarketingOverlay>{"តោះ ស្តាប់មតិយោបល់ទាំងអស់គ្នា"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Cooking confidence" from={Math.round(55.94 * fps)} durationInFrames={Math.round(59.84 * fps) - Math.round(55.94 * fps)} premountFor={fps}>
      <MarketingOverlay>{"ពីមុនមិនហ៊ានធ្វើច្រើន\nឥឡូវមានទំនុកចិត្តធ្វើច្រើនហើយ"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Measured cooking" from={Math.round(60.18 * fps)} durationInFrames={Math.round(64.92 * fps) - Math.round(60.18 * fps)} premountFor={fps}>
      <MarketingOverlay>{"ធ្វើម្ហូបតាមកម្រិត\nឆ្ងាញ់ និងមានទំនុកចិត្ត"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Thanks for trust" from={Math.round(88.46 * fps)} durationInFrames={Math.round(96.76 * fps) - Math.round(88.46 * fps)} premountFor={fps}>
      <MarketingOverlay>{"អរគុណសម្រាប់ការទុកចិត្ត\nនិងការគាំទ្ររហូតមក"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Pchum Ben offering" from={Math.round(117.48 * fps)} durationInFrames={Math.round(119.44 * fps) - Math.round(117.48 * fps)} premountFor={fps}>
      <MarketingOverlay>{"ធ្វើម្ហូបយកទៅប្រកេនលោក\nក្នុងរដូវបុណ្យភ្ជុំបិណ្ឌ"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Thank you students" from={Math.round(122.52 * fps)} durationInFrames={Math.round(130.52 * fps) - Math.round(122.52 * fps)} premountFor={fps}>
      <MarketingOverlay>{"អរគុណដែលជ្រើសរើស\nរៀនធ្វើម្ហូបជាមួយខ្ញុំ"}</MarketingOverlay>
    </Sequence>
    <Sequence name="Pchum Ben wishes" from={Math.round(130.88 * fps)} durationInFrames={Math.round(136.5 * fps) - Math.round(130.88 * fps)} premountFor={fps}>
      <MarketingOverlay>{"សូមឱ្យសុខសប្បាយ រកស៊ីមានបាន\nនិងធ្វើដំណើរប្រកបដោយសុវត្ថិភាព"}</MarketingOverlay>
    </Sequence>
    <Sequence name="New lessons invitation" from={Math.round(138.02 * fps)} durationInFrames={Math.round(142.42 * fps) - Math.round(138.02 * fps)} premountFor={fps}>
      <MarketingOverlay>{"ចង់ចូលរៀនធ្វើម្ហូប?\nឆាតមក មានមេរៀនថ្មីៗទៀត"}</MarketingOverlay>
    </Sequence>
  </AbsoluteFill>;
};

export const RemotionRoot = () => (
  <>
  <Composition id="BusinessContentWorkshopTitle" component={BusinessContentWorkshop} durationInFrames={300} fps={30} width={1920} height={1080} />
    <Composition id="BusinessContentWorkshop" component={WorkshopFootage} durationInFrames={4324} fps={30} width={720} height={1280} />
  </>
);
