# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "beautifulsoup4",
# ]
# ///

import sys
import argparse
from bs4 import BeautifulSoup

def main():
    parser = argparse.ArgumentParser(description="Extract or replace HTML by selector.")
    parser.add_argument("action", choices=["extract", "replace"])
    parser.add_argument("--file", required=True)
    parser.add_argument("--selector", required=True)
    parser.add_argument("--replacement", help="File containing replacement HTML (for replace action)")

    args = parser.parse_args()

    with open(args.file, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    el = soup.select_one(args.selector)
    if not el:
        print(f"Error: Selector '{args.selector}' not found in {args.file}", file=sys.stderr)
        sys.exit(1)

    if args.action == "extract":
        print(str(el))
        
    elif args.action == "replace":
        with open(args.replacement, "r", encoding="utf-8") as f:
            new_html = f.read()
        
        new_soup = BeautifulSoup(new_html, "html.parser")
        
        # Replace the element with the parsed replacement
        el.replace_with(new_soup)
        
        with open(args.file, "w", encoding="utf-8") as f:
            f.write(str(soup))
        print("Element replaced successfully.", file=sys.stderr)

if __name__ == "__main__":
    main()
