with open('vts_7L_test.py', 'r', encoding='utf-8') as f:
    lines = f.read().splitlines()

# The error was at 8571, 8572, 8573
for i in range(len(lines)):
    if 'if spoken.strip(" *\'\\"-.,!?。，！？' in lines[i]:
        lines[i] = '            if spoken.strip(" *\'\\"-.,!?。，！？\\\\n\\\\r"):'
        if lines[i+1] == '':
            lines[i+1] = '                pass # fixed'
        if '"):' in lines[i+2]:
            lines[i+2] = '                pass # fixed'
        break

with open('vts_7L_test.py', 'w', encoding='utf-8') as f:
    f.write('\\n'.join(lines))
