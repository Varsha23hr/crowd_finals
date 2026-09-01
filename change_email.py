with open('config.py', 'r') as f:
    content = f.read()

import re
content = re.sub(r'RECEIVER_EMAIL\s*=\s*\[.*?\]', 'RECEIVER_EMAIL = ["2005sahanahv@gmail.com"]', content)

with open('config.py', 'w') as f:
    f.write(content)

print('Done! Verifying...')
with open('config.py', 'r') as f:
    for line in f:
        if 'RECEIVER_EMAIL' in line:
            print(line.strip())
