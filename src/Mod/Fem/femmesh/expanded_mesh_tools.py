import re


def parse_12d(filepath):
    mode = 0
    element = None
    element_mapping = {}

    def parse(line):
        nonlocal mode, element
        start_pattern = r"\s+ELEMENT\s+(\d+) with label \".*\" and with nodes:"
        ignore_pattern = r".*was generated"
        if mode == 0:
            match = re.match(start_pattern, line)
            if match:
                element_id = int(match.groups()[0])
                element_mapping[element_id] = {"from": [], "to": []}
                element = element_mapping[element_id]
                mode = 1
        elif mode == 1:
            node_line = line.split()
            if len(node_line) == 0:
                raise ValueError(f"expected node indices, read: '{line}'")
            element["from"].extend([int(node) for node in node_line])
            mode = 2
        elif mode == 2:
            pattern = r"\s+is expanded into a \".*\" element with topology:"
            match = re.match(pattern, line)
            if match:
                mode = 3
            else:
                raise ValueError(f"expected is expanded into, read: '{line}'")
        elif mode == 3:
            # keep reading until no more digits
            match = re.match(start_pattern, line)
            if match:
                mode = 0
                return parse(line)
            match = re.match(ignore_pattern, line)
            if match:
                mode = 0
                return parse(line)
            node_line = line.split()
            element["to"].extend([int(node) for node in node_line])
        else:
            assert 0

    with open(filepath, "r") as f:
        while line := f.readline():
            parse(line)

    return element_mapping
