OPTIONS = 4

QUESTIONS = (
    {"id": "w1", "topic": "war", "answer": 2},
    {"id": "w2", "topic": "war", "answer": 1},
    {"id": "w3", "topic": "war", "answer": 2},
    {"id": "w4", "topic": "war", "answer": 1},
    {"id": "w5", "topic": "war", "answer": 1},
    {"id": "w6", "topic": "war", "answer": 0},
    {"id": "c1", "topic": "capital", "answer": 1},
    {"id": "c2", "topic": "capital", "answer": 1},
    {"id": "c3", "topic": "capital", "answer": 2},
    {"id": "c4", "topic": "capital", "answer": 1},
    {"id": "c5", "topic": "capital", "answer": 3},
    {"id": "c6", "topic": "capital", "answer": 0},
    {"id": "a1", "topic": "army", "answer": 2},
    {"id": "a2", "topic": "army", "answer": 2},
    {"id": "a3", "topic": "army", "answer": 2},
    {"id": "a4", "topic": "army", "answer": 0},
    {"id": "a5", "topic": "army", "answer": 3},
    {"id": "a6", "topic": "army", "answer": 1},
    {"id": "n1", "topic": "clan", "answer": 2},
    {"id": "n2", "topic": "clan", "answer": 2},
    {"id": "n3", "topic": "clan", "answer": 3},
    {"id": "n4", "topic": "clan", "answer": 2},
    {"id": "n5", "topic": "clan", "answer": 1},
    {"id": "n6", "topic": "clan", "answer": 1},
)

_BY_ID = {q["id"]: q for q in QUESTIONS}


def by_id(qid):
    return _BY_ID.get(qid)
