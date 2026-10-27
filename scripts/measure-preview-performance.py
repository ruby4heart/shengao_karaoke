"""Source wrapper for the complete measurement shared with the frozen app."""
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'desktop'),str(root/'backend')]
from shengao.performance_acceptance import main

if __name__=='__main__':raise SystemExit(main())
