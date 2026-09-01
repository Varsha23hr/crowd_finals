with open('static/app.js', 'r') as f:
    content = f.read()

# Replace the hardcoded 0 with the actual calculated threshold
content = content.replace(
    'form.append("threshold", 0);',
    'form.append("threshold", calculatedThreshold || 20);'
)

with open('static/app.js', 'w') as f:
    f.write(content)

# Verify
with open('static/app.js', 'r') as f:
    for i, line in enumerate(f.readlines()):
        if 'form.append' in line and 'threshold' in line:
            print(f'{i}: {line.strip()}')
print('Fixed!')
