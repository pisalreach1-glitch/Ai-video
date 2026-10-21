import os
import wave
import struct
import numpy as np

SAMPLE_RATE = 44100

def write_wav(filename: str, audio: np.ndarray):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    # Normalize and clip
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = (audio / peak) * 0.98
    int16_data = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)

    
    with wave.open(filename, "w") as wf:
        wf.setnchannels(1)  # Mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int16_data.tobytes())

def generate_lofi(filename: str, duration: float = 16.0):
    """Mellow Lofi chill chords (Dm7 -> G7 -> Cmaj7 -> Am7) with soft vinyl warmth and rimshots"""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    audio = np.zeros_like(t)
    
    # 4 chords, 4 seconds each
    # Dm7: D3, F3, A3, C4
    # G7: G2, B3, D4, F4
    # Cmaj7: C3, E3, G3, B3
    # Am7: A2, C3, E3, G3
    chords = [
        [146.83, 174.61, 220.00, 261.63], # Dm7
        [98.00,  246.94, 293.66, 349.23], # G7
        [130.81, 164.81, 196.00, 246.94], # Cmaj7
        [110.00, 130.81, 164.81, 196.00], # Am7
    ]
    
    chord_len = duration / len(chords)
    
    for c_idx, chord in enumerate(chords):
        c_start = int(c_idx * chord_len * SAMPLE_RATE)
        c_end = int((c_idx + 1) * chord_len * SAMPLE_RATE)
        t_sub = t[c_start:c_end] - (c_idx * chord_len)
        
        # Soft Rhodes / Electric Piano sound (Fundamental + warm 2nd/3rd harmonics with gentle tremolo)
        tremolo = 1.0 + 0.12 * np.sin(2 * np.pi * 4.5 * t_sub)
        chord_audio = np.zeros_like(t_sub)
        for freq in chord:
            env = np.exp(-t_sub * 0.45) * 0.8 + 0.2
            sine = (
                np.sin(2 * np.pi * freq * t_sub) * 0.6 +
                np.sin(2 * np.pi * freq * 2.0 * t_sub) * 0.25 +
                np.sin(2 * np.pi * freq * 3.0 * t_sub) * 0.12
            )
            chord_audio += sine * env * tremolo
            
        audio[c_start:c_end] += chord_audio * 0.35
        
    # Add gentle chill hip-hop rhythm (soft kick on beats 1 & 3, snare rimshot on 2 & 4, hi-hats on 8ths)
    bpm = 75.0
    beat_dur = 60.0 / bpm
    total_beats = int(duration / beat_dur)
    
    for b in range(total_beats):
        beat_time = b * beat_dur
        b_sample = int(beat_time * SAMPLE_RATE)
        
        # Soft Kick on beat 0, 2, 4, etc.
        if b % 2 == 0:
            k_len = int(SAMPLE_RATE * 0.25)
            if b_sample + k_len < len(audio):
                k_t = np.linspace(0, 0.25, k_len)
                k_freq = 80 * np.exp(-k_t * 18.0) + 38
                k_env = np.exp(-k_t * 12.0)
                audio[b_sample:b_sample + k_len] += np.sin(2 * np.pi * k_freq * k_t) * k_env * 0.45
                
        # Soft Snare/Rimshot on beat 1, 3, etc.
        if b % 2 == 1:
            s_len = int(SAMPLE_RATE * 0.15)
            if b_sample + s_len < len(audio):
                s_t = np.linspace(0, 0.15, s_len)
                noise = np.random.uniform(-0.15, 0.15, s_len)
                s_env = np.exp(-s_t * 22.0)
                tone = np.sin(2 * np.pi * 220 * s_t) * 0.3
                audio[b_sample:b_sample + s_len] += (noise + tone) * s_env * 0.35
                
    # Soft vinyl warmth noise
    vinyl_noise = np.random.uniform(-0.02, 0.02, len(audio))
    audio += vinyl_noise
    
    write_wav(filename, audio)

def generate_upbeat(filename: str, duration: float = 16.0):
    """Upbeat, cheerful motivational pop groove (120 BPM, bright major arpeggios, energetic pulse)"""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    audio = np.zeros_like(t)
    
    bpm = 118.0
    beat_dur = 60.0 / bpm
    eighth_dur = beat_dur / 2.0
    total_eighths = int(duration / eighth_dur)
    
    # Chord roots: C (261), G (196), Am (220), F (174)
    prog_roots = [261.63, 196.00, 220.00, 174.61]
    
    for i in range(total_eighths):
        note_time = i * eighth_dur
        n_sample = int(note_time * SAMPLE_RATE)
        root_idx = int(i / 8) % len(prog_roots)
        root = prog_roots[root_idx]
        
        # Bright plucky acoustic/synth notes
        chord_intervals = [1.0, 1.25, 1.5, 2.0]
        interval = chord_intervals[i % 4]
        freq = root * interval
        
        p_len = int(SAMPLE_RATE * 0.18)
        if n_sample + p_len < len(audio):
            p_t = np.linspace(0, 0.18, p_len)
            p_env = np.exp(-p_t * 14.0)
            synth = (
                np.sin(2 * np.pi * freq * p_t) * 0.7 +
                np.sin(2 * np.pi * freq * 2.0 * p_t) * 0.25 +
                np.sin(2 * np.pi * freq * 4.0 * p_t) * 0.1
            )
            audio[n_sample:n_sample + p_len] += synth * p_env * 0.32
            
        # Driving 4-on-the-floor pop kick on every beat
        if i % 2 == 0:
            k_len = int(SAMPLE_RATE * 0.2)
            if n_sample + k_len < len(audio):
                k_t = np.linspace(0, 0.2, k_len)
                k_freq = 110 * np.exp(-k_t * 22.0) + 45
                k_env = np.exp(-k_t * 14.0)
                audio[n_sample:n_sample + k_len] += np.sin(2 * np.pi * k_freq * k_t) * k_env * 0.45
                
        # Upbeat clap / snare on beats 2 & 4
        if i % 4 == 2:
            c_len = int(SAMPLE_RATE * 0.14)
            if n_sample + c_len < len(audio):
                c_t = np.linspace(0, 0.14, c_len)
                noise = np.random.uniform(-0.25, 0.25, c_len) * np.exp(-c_t * 20.0)
                audio[n_sample:n_sample + c_len] += noise * 0.4
                
    write_wav(filename, audio)

def generate_hype(filename: str, duration: float = 16.0):
    """Hype / Phonk motivational drive (deep sliding 808 bass + rhythmic cowbell/synth pulse)"""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    audio = np.zeros_like(t)
    
    bpm = 125.0
    beat_dur = 60.0 / bpm
    total_beats = int(duration / beat_dur)
    
    # Bass notes: F (43.65), Ab (51.91), Bb (58.27), C (65.41)
    bass_notes = [43.65, 51.91, 58.27, 43.65]
    
    for b in range(total_beats):
        b_time = b * beat_dur
        b_sample = int(b_time * SAMPLE_RATE)
        bass_freq = bass_notes[(b // 4) % len(bass_notes)]
        
        # Heavy 808 Sub-Bass Kick
        b_len = int(SAMPLE_RATE * 0.38)
        if b_sample + b_len < len(audio):
            b_t = np.linspace(0, 0.38, b_len)
            f_slide = bass_freq * 1.5 * np.exp(-b_t * 8.0) + bass_freq
            b_env = np.exp(-b_t * 4.5)
            # Saturated bass
            raw = np.sin(2 * np.pi * f_slide * b_t) * 1.4
            saturated = np.tanh(raw) * 0.55
            audio[b_sample:b_sample + b_len] += saturated * b_env
            
        # Crisp hi-hat & metallic bell accent
        h_len = int(SAMPLE_RATE * 0.08)
        if b_sample + h_len < len(audio):
            h_t = np.linspace(0, 0.08, h_len)
            noise = np.random.uniform(-0.15, 0.15, h_len) * np.exp(-h_t * 35.0)
            bell = np.sin(2 * np.pi * 1174.66 * h_t) * 0.25 * np.exp(-h_t * 18.0)
            audio[b_sample:b_sample + h_len] += (noise + bell) * 0.3
            
    write_wav(filename, audio)

def main():
    music_dir = os.path.join("remotion", "public", "music")
    generate_lofi(os.path.join(music_dir, "lofi.wav"))
    generate_upbeat(os.path.join(music_dir, "upbeat.wav"))
    generate_hype(os.path.join(music_dir, "hype.wav"))
    print("[SUCCESS] All 3 BGM audio tracks generated successfully in remotion/public/music/!")

if __name__ == "__main__":
    main()
