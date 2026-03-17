from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PrefixTrieNode:
    node_id: int
    depth: int
    block_hash: str | None
    children: dict[str, "PrefixTrieNode"] = field(default_factory=dict)


class PrefixTrie:
    def __init__(self) -> None:
        self._next_node_id = 1
        self.root = PrefixTrieNode(node_id=0, depth=0, block_hash=None)

    def match_prefix_length(self, blocks: tuple[str, ...]) -> int:
        current = self.root
        matched = 0
        for block in blocks:
            child = current.children.get(block)
            if child is None:
                break
            matched += 1
            current = child
        return matched

    def insert(self, blocks: tuple[str, ...]) -> None:
        current = self.root
        for block in blocks:
            child = current.children.get(block)
            if child is None:
                child = PrefixTrieNode(
                    node_id=self._next_node_id,
                    depth=current.depth + 1,
                    block_hash=block,
                )
                current.children[block] = child
                self._next_node_id += 1
            current = child

    def match_and_insert(self, blocks: tuple[str, ...]) -> int:
        matched, _ = self.match_and_insert_path(blocks)
        return matched

    def match_and_insert_path(self, blocks: tuple[str, ...]) -> tuple[int, tuple[int, ...]]:
        current = self.root
        matched = 0
        node_ids: list[int] = []
        for block in blocks:
            child = current.children.get(block)
            if child is None:
                child = PrefixTrieNode(
                    node_id=self._next_node_id,
                    depth=current.depth + 1,
                    block_hash=block,
                )
                current.children[block] = child
                self._next_node_id += 1
            else:
                if matched == len(node_ids):
                    matched += 1
            node_ids.append(child.node_id)
            current = child
        return matched, tuple(node_ids)
