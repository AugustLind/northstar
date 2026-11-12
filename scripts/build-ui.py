"""Compose the checked-in HTML shell or verify that it is current."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ui_templates

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    target=ui_templates.ROOT/'static/index.html';expected=ui_templates.render()
    if args.check:
        if target.read_text()!=expected:raise SystemExit('UI HTML is stale. Run python3 scripts/build-ui.py.')
        print('UI templates and generated index match.')
    else:target.write_text(expected);print('Composed static/index.html from workspace templates.')
if __name__=='__main__':main()
