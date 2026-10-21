import os
import wave
import struct
import math
import random

SAMPLE_RATE = 44100

def create_wav(filename: str, samples: list):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with wave.open(filename, "w") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(SAMPLE_RATE)
        
        # Clip and pack to 16-bit PCM
        packed_data = bytearray()
        for s in samples:
            val = max(-1.0, min(1.0, s))
            packed_data.extend(struct.pack("<h", int(val * 32767.0)))
        wav_file.writeframes(packed_data)

def generate_whoosh(filename: str, duration: float = 0.35):
    """Cinematic fast whoosh / swoosh for camera punch-in jump cuts"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    
    # Filtered white noise with bell-shaped amplitude envelope and pitch sweep
    noise_buffer = [random.uniform(-1.0, 1.0) for _ in range(total_samples)]
    
    # Simple lowpass filter simulation
    filtered = []
    alpha = 0.25
    prev = 0.0
    for n in noise_buffer:
        curr = prev + alpha * (n - prev)
        filtered.append(curr)
        prev = curr
        
    for i in range(total_samples):
        t = i / total_samples
        # Bell curve envelope peaked around t=0.4
        envelope = math.sin(t * math.pi) ** 2.2
        # Add a sweeping sine undertone
        freq = 150 + 400 * math.sin(t * math.pi)
        sine = 0.35 * math.sin(2 * math.pi * freq * (i / SAMPLE_RATE))
        sample = (filtered[i] * 0.75 + sine) * envelope * 0.85
        samples.append(sample)
        
    create_wav(filename, samples)

def generate_pop(filename: str, duration: float = 0.12):
    """Clean punchy pop / bubble sound for subtitle text bounce"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        # Rapid pitch drop from 1200Hz to 200Hz
        progress = i / total_samples
        freq = 1200 * math.exp(-progress * 5.0) + 180
        # Fast exponential decay
        envelope = math.exp(-progress * 9.0) * math.sin(min(1.0, progress * 15.0) * (math.pi / 2))
        sample = math.sin(2 * math.pi * freq * t) * envelope * 0.9
        samples.append(sample)
    create_wav(filename, samples)

def generate_ding(filename: str, duration: float = 0.5):
    """Bright metallic bell / chime for key tips and lightbulb moments"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    f1, f2, f3 = 1760.0, 3520.0, 5280.0
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        envelope = math.exp(-progress * 4.5)
        # Harmonic bell mix
        s = 0.6 * math.sin(2 * math.pi * f1 * t) + \
            0.3 * math.sin(2 * math.pi * f2 * t) + \
            0.15 * math.sin(2 * math.pi * f3 * t)
        samples.append(s * envelope * 0.8)
    create_wav(filename, samples)

def generate_cash(filename: str, duration: float = 0.45):
    """Cash register / Cha-ching dual chime for money and success"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    f1, f2 = 2093.0, 2793.8  # C7 and F7 bright musical interval
    split_sample = int(total_samples * 0.25)
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        envelope = math.exp(-progress * 5.0)
        # Second ping comes in after split
        s1 = 0.5 * math.sin(2 * math.pi * f1 * t)
        s2 = 0.6 * math.sin(2 * math.pi * f2 * t) if i > split_sample else 0.0
        sample = (s1 + s2) * envelope * 0.85
        samples.append(sample)
    create_wav(filename, samples)

def generate_thud(filename: str, duration: float = 0.25):
    """Sub-bass punch / impact for important emphasis or mistake/warning"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        freq = 140 * math.exp(-progress * 6.0) + 40
        envelope = math.exp(-progress * 7.0)
        sample = math.sin(2 * math.pi * freq * t) * envelope * 0.95
        samples.append(sample)
    create_wav(filename, samples)

def generate_click(filename: str, duration: float = 0.08):
    """Sharp mechanical click for buttons, UI, tech, and steps"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        freq = 2800 * math.exp(-progress * 15.0) + 800
        envelope = math.exp(-progress * 22.0)
        noise = random.uniform(-0.3, 0.3) * envelope
        sample = (math.sin(2 * math.pi * freq * t) * 0.7 + noise) * envelope
        samples.append(sample * 0.9)
    create_wav(filename, samples)

def generate_camera(filename: str, duration: float = 0.22):
    """Camera shutter snap (double click-clack) for photos, seeing, memories"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    click1_end = int(total_samples * 0.35)
    click2_start = int(total_samples * 0.45)
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        if i < click1_end:
            sub_prog = i / click1_end
            env = math.exp(-sub_prog * 18.0)
            freq = 2400 * math.exp(-sub_prog * 12.0) + 600
            s = math.sin(2 * math.pi * freq * t) * env
        elif i >= click2_start:
            sub_prog = (i - click2_start) / (total_samples - click2_start)
            env = math.exp(-sub_prog * 16.0)
            freq = 1800 * math.exp(-sub_prog * 10.0) + 400
            s = (math.sin(2 * math.pi * freq * t) + random.uniform(-0.2, 0.2)) * env
        else:
            s = 0.0
        samples.append(s * 0.85)
    create_wav(filename, samples)

def generate_buzzer(filename: str, duration: float = 0.30):
    """Harsh dual-tone error buzzer for mistakes, warnings, and wrong items"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    f1, f2 = 145.0, 155.0  # Dissonant beating low frequency
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        # Flat sustain with fast drop-off at end
        env = 1.0 if progress < 0.85 else (1.0 - (progress - 0.85) / 0.15)
        # Square wave / clipped sine for rich buzzy timbre
        s1 = 1.0 if math.sin(2 * math.pi * f1 * t) > 0 else -1.0
        s2 = 1.0 if math.sin(2 * math.pi * f2 * t) > 0 else -1.0
        sample = (0.5 * s1 + 0.5 * s2) * env * 0.75
        samples.append(sample)
    create_wav(filename, samples)

def generate_tada(filename: str, duration: float = 0.55):
    """Cheerful celebratory victory fanfare / level up chime"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    # Musical chord arpeggio: C5 (523), E5 (659), G5 (784), C6 (1046)
    notes = [523.25, 659.25, 783.99, 1046.50]
    note_dur = total_samples / 4.0
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        note_idx = min(3, int(i / note_dur))
        freq = notes[note_idx]
        note_progress = (i - note_idx * note_dur) / note_dur
        # Note decay envelope
        env = math.exp(-note_progress * 3.5) if note_idx < 3 else math.exp(-note_progress * 2.2)
        sample = (math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(4 * math.pi * freq * t)) * env * 0.8
        samples.append(sample)
    create_wav(filename, samples)

def generate_sparkle(filename: str, duration: float = 0.50):
    """Magical shimmer / twinkle for secrets, beauty, and amazing reveals"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    sparkle_freqs = [2093.0, 2637.0, 3136.0, 4186.0]
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        env = math.sin(progress * math.pi) ** 1.5 * math.exp(-progress * 2.0)
        s = 0.0
        for idx, f in enumerate(sparkle_freqs):
            phase_offset = idx * 0.08
            t_adj = max(0.0, t - phase_offset)
            s += 0.25 * math.sin(2 * math.pi * f * t_adj) * math.exp(-t_adj * 6.0)
        samples.append(s * env * 0.9)
    create_wav(filename, samples)

def generate_riser(filename: str, duration: float = 0.50):
    """Tension build sweep / pitch riser for questions, mysteries, and punchlines"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        progress = i / total_samples
        # Exponential frequency rise from 120Hz to 950Hz
        freq = 120 + 830 * (progress ** 2.2)
        env = (progress ** 1.8) * 0.85
        noise = random.uniform(-0.15, 0.15) * progress
        sample = (math.sin(2 * math.pi * freq * t) * 0.8 + noise) * env
        samples.append(sample)
    create_wav(filename, samples)

def generate_heartbeat(filename: str, duration: float = 0.45):
    """Low-sub dramatic double-thump for shock, danger, tension, and emotion"""
    total_samples = int(SAMPLE_RATE * duration)
    samples = []
    beat1_len = int(total_samples * 0.35)
    beat2_start = int(total_samples * 0.40)
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        if i < beat1_len:
            prog = i / beat1_len
            freq = 68 * math.exp(-prog * 4.0) + 38
            env = math.exp(-prog * 6.0)
            s = math.sin(2 * math.pi * freq * t) * env * 0.95
        elif i >= beat2_start:
            prog = (i - beat2_start) / (total_samples - beat2_start)
            freq = 60 * math.exp(-prog * 4.0) + 35
            env = math.exp(-prog * 5.0)
            s = math.sin(2 * math.pi * freq * t) * env * 0.85
        else:
            s = 0.0
        samples.append(s)
    create_wav(filename, samples)

def main():
    sfx_dir = os.path.join("remotion", "public", "sfx")
    generate_whoosh(os.path.join(sfx_dir, "whoosh.wav"))
    generate_pop(os.path.join(sfx_dir, "pop.wav"))
    generate_ding(os.path.join(sfx_dir, "ding.wav"))
    generate_cash(os.path.join(sfx_dir, "cash.wav"))
    generate_thud(os.path.join(sfx_dir, "thud.wav"))
    generate_click(os.path.join(sfx_dir, "click.wav"))
    generate_camera(os.path.join(sfx_dir, "camera.wav"))
    generate_buzzer(os.path.join(sfx_dir, "buzzer.wav"))
    generate_tada(os.path.join(sfx_dir, "tada.wav"))
    generate_sparkle(os.path.join(sfx_dir, "sparkle.wav"))
    generate_riser(os.path.join(sfx_dir, "riser.wav"))
    generate_heartbeat(os.path.join(sfx_dir, "heartbeat.wav"))
    print("[SUCCESS] All 12 SFX audio files generated successfully in remotion/public/sfx/!")

if __name__ == "__main__":
    main()
