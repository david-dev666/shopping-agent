"""CLI：打印规则层评测结果。

用法（在 backend/ 下）：
    uv run python scripts/eval_rules.py
    uv run python scripts/eval_rules.py --verbose   # 打印判错的用例
"""

import argparse

from eval.rules import evaluate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="打印判错的用例")
    args = parser.parse_args()

    m = evaluate()
    if args.verbose:
        for e in m["errors"]:
            print(
                f"  ✗ [{e['query']}] {e['title'][:30]}"
                f"  期望{e['expect'] or '[]'} 实际{e['got'] or '[]'}"
            )

    print(f"\n{'rule':16}{'P':>8}{'R':>8}{'F1':>8}{'TP':>5}{'FP':>5}{'FN':>5}")
    for rule, s in m["per_rule"].items():
        print(f"{rule:16}{s['precision']:8.2f}{s['recall']:8.2f}{s['f1']:8.2f}"
              f"{s['tp']:5d}{s['fp']:5d}{s['fn']:5d}")
    mic = m["micro"]
    print(f"{'micro':16}{mic['precision']:8.2f}{mic['recall']:8.2f}{mic['f1']:8.2f}"
          f"{mic['tp']:5d}{mic['fp']:5d}{mic['fn']:5d}")
    print(f"\n用例数: {m['n_cases']}")


if __name__ == "__main__":
    main()
