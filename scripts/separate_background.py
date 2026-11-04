"""Isolated UVR inference: export only the non-vocal stem, never original speech."""
import argparse
import logging
from pathlib import Path
import shutil

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--models', required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    from audio_separator.separator import Separator
    output = Path(args.output).resolve()
    separator = Separator(
        log_level=logging.WARNING, output_dir=str(output.parent),
        model_file_dir=str(Path(args.models).resolve()), output_format='WAV',
        output_single_stem='Instrumental', normalization_threshold=0.95,
        mdx_params={'hop_length': 1024, 'segment_size': 256, 'overlap': 0.25,
                    'batch_size': 1, 'enable_denoise': False},
    )
    separator.load_model(model_filename=args.model)
    files = separator.separate(str(Path(args.input).resolve()))
    candidates = []
    for file in files:
        path = Path(file)
        if not path.is_absolute():
            path = output.parent / path
        if path.is_file() and 'instrumental' in path.name.lower():
            candidates.append(path)
    if len(candidates) != 1:
        raise RuntimeError('Separator did not produce exactly one instrumental stem')
    shutil.copyfile(candidates[0], output)

if __name__ == '__main__':
    main()
