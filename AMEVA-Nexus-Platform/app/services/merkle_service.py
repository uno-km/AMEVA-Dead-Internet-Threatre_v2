import hashlib

def get_leaf_hash(site_id: str, experiment_id: str, agent_id: str, amount: float, nonce: str) -> str:
    """
    Leaf 노드의 해시를 계산합니다. (Sorted Merkle 호환)
    sha256(site_id + ":" + experiment_id + ":" + agent_id + ":" + str(amount) + ":" + nonce)
    """
    message = f"{site_id}:{experiment_id}:{agent_id}:{amount}:{nonce}".encode("utf-8")
    return hashlib.sha256(message).hexdigest()

def create_merkle_tree(leaves: list[str]) -> tuple[str, dict[str, list[str]]]:
    """
    주어진 leaf 해시 리스트로부터 Merkle Root와 각 leaf의 Proof 리스트를 반환합니다.
    정렬식 Merkle Tree (Sorted Merkle Tree)로 빌드합니다.
    """
    if not leaves:
        empty_root = hashlib.sha256(b"").hexdigest()
        return empty_root, {}

    # 유일성 정렬 보장
    leaves = sorted(list(set(leaves)))

    if len(leaves) == 1:
        return leaves[0], {leaves[0]: []}

    # 각 레벨의 노드를 저장할 트리
    tree = [leaves.copy()]
    
    # 리프 노드 인덱스 추적용
    # Sorted Merkle Tree에서는 결합할 때 정렬하여 결합하므로
    # 해싱 과정에서 left / right 결합 방향이 각 level 마다 다릅니다.
    # 이를 위해 단순 바이너리 인덱스로 추적하며 proof를 빌드합니다.
    while len(tree[-1]) > 1:
        current_level = tree[-1]
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            if i + 1 < len(current_level):
                right = current_level[i+1]
            else:
                right = left  # 홀수개 복제
            
            # 결합 시 정렬하여 해싱 (Sorted Merkle)
            if left <= right:
                combined = (left + right).encode("utf-8")
            else:
                combined = (right + left).encode("utf-8")
            next_level.append(hashlib.sha256(combined).hexdigest())
        tree.append(next_level)

    root = tree[-1][0]
    proofs = {}

    for idx, leaf in enumerate(leaves):
        proof = []
        current_idx = idx
        for level in range(len(tree) - 1):
            level_nodes = tree[level]
            if current_idx % 2 == 0:
                sibling_idx = current_idx + 1 if current_idx + 1 < len(level_nodes) else current_idx
            else:
                sibling_idx = current_idx - 1
            
            proof.append(level_nodes[sibling_idx])
            current_idx = current_idx // 2
        proofs[leaf] = proof

    return root, proofs

def verify_merkle_proof(root_hash: str, leaf_hash: str, proof: list[str]) -> bool:
    """
    Sorted Merkle Proof를 검증합니다.
    """
    current_hash = leaf_hash
    for sibling in proof:
        if current_hash <= sibling:
            combined = (current_hash + sibling).encode("utf-8")
        else:
            combined = (sibling + current_hash).encode("utf-8")
        current_hash = hashlib.sha256(combined).hexdigest()
        
    return current_hash == root_hash
