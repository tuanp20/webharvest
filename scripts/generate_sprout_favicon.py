import os
import sys

# Ensure import works by adding the current directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from generate_favicon import main

if __name__ == '__main__':
    main()
