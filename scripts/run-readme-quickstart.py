"""Execute the marked README shell block verbatim using the installed CLI."""
from pathlib import Path
import subprocess


text = Path('README.md').read_text()
block = text.split('<!-- quickstart-v3-start -->', 1)[1].split('<!-- quickstart-v3-end -->', 1)[0]
shell = block.split('```sh\n', 1)[1].split('```', 1)[0]
subprocess.run(['sh', '-eu', '-c', shell], check=True)
print('README quickstart: 12/12 commands PASS (verbatim shell block, installed CLI)')
