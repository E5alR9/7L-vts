import sys
print('sys.path[0]:', sys.path[0])
print('RVC in path:', any('RVC-WebUI' in p for p in sys.path))
print('CWD:', __import__('os').getcwd())
