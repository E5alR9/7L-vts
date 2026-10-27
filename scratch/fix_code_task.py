import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

p = "vts_7L_test.py"
s = open(p, encoding="utf-8").read()

a = "{reply_text}\")\n    except Exception as e:\n        log_print(f\"\u274c [\u7a0b\u5f0f\u5c08\u5bb6\u932f\u8aa4] {e}\")"
assert s.count(a) == 1, s.count(a)
s = s.replace(a, "{_clean_result_for_brain(reply_text)}\")\n    except Exception as e:\n        log_print(f\"\u274c [\u7a0b\u5f0f\u5c08\u5bb6\u932f\u8aa4] {e}\")")

b = "\u547c\u53eb [TOOL:CODE] \u5931\u6557\u3002"
assert s.count(b) == 1, s.count(b)
s = s.replace(b, "\u7a0b\u5f0f\u5206\u6790\u529f\u80fd\u66ab\u6642\u5931\u6557\u3002")

open(p, "w", encoding="utf-8", newline="").write(s)
print("code task cleaned")
