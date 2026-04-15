from eval.runner import run_eval
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--cases", default="eval/cases.jsonl")
parser.add_argument("--layer", type=int, default=1)
parser.add_argument("--out-dir", default="eval/runs")
args = parser.parse_args()
run_eval(args.cases, args.layer, args.out_dir)
