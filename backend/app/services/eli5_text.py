
DEFAULT_LANG = "zh-TW"
_SUPPORTED_LANGS = ("zh-TW", "en")

def normalize_lang(lang):
    if not lang:
        return DEFAULT_LANG
    if lang in _SUPPORTED_LANGS:
        return lang
    return "en" if lang.lower().startswith("en") else DEFAULT_LANG

TYPE_LABELS = {
    "zh-TW": {
        "odm": "ODM 專案型",
        "standard": "標準品型",
    },
    "en": {
        "odm": "ODM Project",
        "standard": "Standard Product",
    },
}

SCENARIOS = {
    "zh-TW": {
        "S0": {
            "odm": {"title": "新客戶，營收還沒有目標可比", "action": "明年用今年的營收當基準訂目標"},
            "standard": {"title": "新客戶，營收還沒有目標可比", "action": "明年用今年的營收當基準訂目標"},
        },
        "S1": {
            "odm": {"title": "今年兩項都達標", "action": "維持住，明年的目標可以討論要不要拉高"},
            "standard": {"title": "今年兩項都達標", "action": "維持住，明年的目標可以討論要不要拉高"},
        },
        "S2": {
            "odm": {"title": "營收達標了，毛利沒達標", "action": "跟業務確認差距的主要原因"},
            "standard": {"title": "營收達標了，毛利沒達標", "action": "跟業務確認差距的主要原因"},
        },
        "S3": {
            "odm": {"title": "毛利守住了，營收沒達標", "action": "跟業務確認差距的主要原因"},
            "standard": {"title": "毛利守住了，營收沒達標", "action": "跟業務確認差距的主要原因"},
        },
        "S4": {
            "odm": {"title": "今年兩項都沒達標", "action": "跟業務確認差距的主要原因"},
            "standard": {"title": "今年兩項都沒達標", "action": "跟業務確認差距的主要原因"},
        },
        "A": {
            "odm": {
                "title": "訂單筆數變多，但總營收沒跟上",
                "action": "查是不是年度降價談掉了，並確認毛利還守得住",
            },
            "standard": {
                "title": "訂單筆數變多，但總營收沒跟上",
                "action": "查是不是被競品分食了，並確認毛利還守得住",
            },
        },
        "B": {
            "odm": {
                "title": "訂單筆數變少，但總營收反而成長",
                "action": "確認下一個專案接得上",
            },
            "standard": {
                "title": "訂單筆數變少，但總營收反而成長",
                "action": "確認訂單沒有過度集中在一兩筆",
            },
        },
        "C": {
            "odm": {
                "title": "接下來半年可能會沒單進來",
                "action": "現在就要談下一個案子，否則半年後會斷",
            },
            "standard": {
                "title": "接下來半年的需求會掉",
                "action": "現在就要補商機，否則半年後會斷",
            },
        },
        "D": {
            "odm": {
                "title": "接下來會有一批新的量進來",
                "action": "追緊這批新專案的成交時程，量大的先讓生管心裡有數",
            },
            "standard": {
                "title": "接下來的案源會放大",
                "action": "追緊這批商機的成交時程，量大的先讓生管心裡有數",
            },
        },
        "E": {
            "odm": {
                "title": "訂單堆著出不掉",
                "action": "跟生管確認出貨日與料況，先跟客戶把交期講清楚",
            },
            "standard": {
                "title": "訂單堆著出不掉",
                "action": "跟生管確認出貨日與料況，先跟客戶把交期講清楚",
            },
        },
        "F": {
            "odm": {
                "title": "先前接的單正在大量出貨",
                "action": "確認後續專案的立案進度，量產出完後產線才不會空",
            },
            "standard": {
                "title": "在吃舊訂單，新單沒補上",
                "action": "確認積壓消化完之後還有沒有單，也提醒生管別再多備料",
            },
        },
        "G": {
            "odm": {
                "title": "兩邊同步，沒有特別的事",
                "action": "",
            },
            "standard": {
                "title": "兩邊同步，沒有特別的事",
                "action": "",
            },
        },
        "H": {
            "odm": {
                "title": "訂單和金額一起在成長",
                "action": "確認是哪幾個機種在帶動，明年目標跟著調整",
            },
            "standard": {
                "title": "訂單和金額一起在成長",
                "action": "確認是哪幾個機種在帶動，明年目標跟著調整",
            },
        },
        "I": {
            "odm": {
                "title": "訂單和金額一起在掉",
                "action": "查是不是專案結束了沒有接續",
            },
            "standard": {
                "title": "訂單和金額一起在掉",
                "action": "查是不是被競品取代了",
            },
        },
        "J": {
            "odm": {"title": "爭取的案子，多數沒拿到", "action": "最常見的敗因是「{reason}」，下一案報價前先把這一點補起來"},
            "standard": {"title": "爭取的案子，多數沒拿到", "action": "最常見的敗因是「{reason}」，下一案報價前先把這一點補起來"},
        },
        "K": {
            "odm": {"title": "爭取的案子，拿到的遠多過丟掉的", "action": "維持住，追蹤贏到的案子有沒有如期轉成訂單"},
            "standard": {"title": "爭取的案子，拿到的遠多過丟掉的", "action": "維持住，追蹤贏到的案子有沒有如期轉成訂單"},
        },
        "L": {
            "odm": {"title": "拿到的和丟掉的差不多", "action": "最常見的敗因是「{reason}」，下一案先把這一點補起來"},
            "standard": {"title": "拿到的和丟掉的差不多", "action": "最常見的敗因是「{reason}」，下一案先把這一點補起來"},
        },
        "M": {
            "odm": {"title": "單變多了，但交期在變差", "action": "跟生管確認是哪幾個機種卡在產能或料況，先跟客戶講好交期——這一項是我們自己的問題"},
            "standard": {"title": "單變多了，但交期在變差", "action": "跟生管確認是哪幾個機種卡在產能或料況，先跟客戶講好交期——這一項是我們自己的問題"},
        },
        "N": {
            "odm": {"title": "訂單在掉，交期也在變差", "action": "跟生管一起把交期守住，別讓它變成下一次的失單理由"},
            "standard": {"title": "訂單在掉，交期也在變差", "action": "跟生管一起把交期守住，別讓它變成下一次的失單理由"},
        },
        "P": {
            "odm": {"title": "訂單差不多，但交期在變差", "action": "量沒變卻交不準，跟生管確認是產能還是料況卡住——這一項是我們自己的問題"},
            "standard": {"title": "訂單差不多，但交期在變差", "action": "量沒變卻交不準，跟生管確認是產能還是料況卡住——這一項是我們自己的問題"},
        },
        "O": {
            "odm": {"title": "準交率只小幅波動", "action": "維持住，這是續單的基礎"},
            "standard": {"title": "準交率只小幅波動", "action": "維持住，這是續單的基礎"},
        },
        "NA": {
            "odm": {
                "title": "去年同期沒有資料，沒得比",
                "action": "",
            },
            "standard": {
                "title": "去年同期沒有資料，沒得比",
                "action": "",
            },
        },
    },
    "en": {
        "S0": {
            "odm": {"title": "New customer — no revenue target to compare yet", "action": "Use this year's revenue as the baseline for next year's target"},
            "standard": {"title": "New customer — no revenue target to compare yet", "action": "Use this year's revenue as the baseline for next year's target"},
        },
        "S1": {
            "odm": {"title": "Both targets met this year", "action": "Keep it up — worth discussing whether to raise next year's targets"},
            "standard": {"title": "Both targets met this year", "action": "Keep it up — worth discussing whether to raise next year's targets"},
        },
        "S2": {
            "odm": {"title": "Revenue target met, margin missed", "action": "Check with sales on the main reason for the gap"},
            "standard": {"title": "Revenue target met, margin missed", "action": "Check with sales on the main reason for the gap"},
        },
        "S3": {
            "odm": {"title": "Margin held, revenue missed", "action": "Check with sales on the main reason for the gap"},
            "standard": {"title": "Margin held, revenue missed", "action": "Check with sales on the main reason for the gap"},
        },
        "S4": {
            "odm": {"title": "Both targets missed this year", "action": "Check with sales on the main reason for the gap"},
            "standard": {"title": "Both targets missed this year", "action": "Check with sales on the main reason for the gap"},
        },
        "A": {
            "odm": {
                "title": "Order count is up, but total revenue hasn't kept pace",
                "action": "Check whether an annual price cut ate into it, and confirm margin still holds",
            },
            "standard": {
                "title": "Order count is up, but total revenue hasn't kept pace",
                "action": "Check whether a competitor is taking share, and confirm margin still holds",
            },
        },
        "B": {
            "odm": {
                "title": "Order count is down, but total revenue grew instead",
                "action": "Confirm the next project is lined up",
            },
            "standard": {
                "title": "Order count is down, but total revenue grew instead",
                "action": "Confirm orders aren't overly concentrated in one or two deals",
            },
        },
        "C": {
            "odm": {
                "title": "Orders may dry up over the next six months",
                "action": "Start working the next deal now, or it will go quiet in six months",
            },
            "standard": {
                "title": "Demand looks set to drop over the next six months",
                "action": "Start building pipeline now, or it will go quiet in six months",
            },
        },
        "D": {
            "odm": {
                "title": "A new wave of volume is coming",
                "action": "Stay on top of when these new projects close, and give production a heads-up if the volume is large",
            },
            "standard": {
                "title": "The pipeline ahead is growing",
                "action": "Stay on top of when these deals close, and give production a heads-up if the volume is large",
            },
        },
        "E": {
            "odm": {
                "title": "Orders are piling up and not shipping",
                "action": "Check ship dates and material status with production, and set clear expectations with the customer",
            },
            "standard": {
                "title": "Orders are piling up and not shipping",
                "action": "Check ship dates and material status with production, and set clear expectations with the customer",
            },
        },
        "F": {
            "odm": {
                "title": "Previously booked orders are shipping in volume",
                "action": "Confirm the follow-on project's status so the line doesn't sit idle once this volume ships out",
            },
            "standard": {
                "title": "Working through backlog, with no new orders replacing it",
                "action": "Confirm there's still business once the backlog clears, and flag production not to over-stock materials",
            },
        },
        "G": {
            "odm": {
                "title": "Both sides moving together, nothing unusual",
                "action": "",
            },
            "standard": {
                "title": "Both sides moving together, nothing unusual",
                "action": "",
            },
        },
        "H": {
            "odm": {
                "title": "Orders and revenue growing together",
                "action": "Confirm which models are driving it, and adjust next year's target accordingly",
            },
            "standard": {
                "title": "Orders and revenue growing together",
                "action": "Confirm which models are driving it, and adjust next year's target accordingly",
            },
        },
        "I": {
            "odm": {
                "title": "Orders and revenue declining together",
                "action": "Check whether the project ended without a follow-on",
            },
            "standard": {
                "title": "Orders and revenue declining together",
                "action": "Check whether a competitor has taken over",
            },
        },
        "J": {
            "odm": {"title": "Most of the deals pursued were not won", "action": 'The most common loss reason is "{reason}" — fix that before quoting the next deal'},
            "standard": {"title": "Most of the deals pursued were not won", "action": 'The most common loss reason is "{reason}" — fix that before quoting the next deal'},
        },
        "K": {
            "odm": {"title": "Deals won far outnumber deals lost", "action": "Keep it up — track whether the won deals turn into orders on schedule"},
            "standard": {"title": "Deals won far outnumber deals lost", "action": "Keep it up — track whether the won deals turn into orders on schedule"},
        },
        "L": {
            "odm": {"title": "Wins and losses are about even", "action": 'The most common loss reason is "{reason}" — fix that before the next deal'},
            "standard": {"title": "Wins and losses are about even", "action": 'The most common loss reason is "{reason}" — fix that before the next deal'},
        },
        "M": {
            "odm": {"title": "Orders are up, but on-time delivery is slipping", "action": "Check with production which models are stuck on capacity or materials, and set expectations with the customer — this one's on us"},
            "standard": {"title": "Orders are up, but on-time delivery is slipping", "action": "Check with production which models are stuck on capacity or materials, and set expectations with the customer — this one's on us"},
        },
        "N": {
            "odm": {"title": "Orders are down, and on-time delivery is slipping too", "action": "Work with production to hold the line on delivery — don't let it become the reason for the next lost order"},
            "standard": {"title": "Orders are down, and on-time delivery is slipping too", "action": "Work with production to hold the line on delivery — don't let it become the reason for the next lost order"},
        },
        "P": {
            "odm": {"title": "Order volume is flat, but on-time delivery is slipping", "action": "Volume hasn't changed but delivery is slipping — check with production planning whether capacity or materials are the bottleneck; this one's on us"},
            "standard": {"title": "Order volume is flat, but on-time delivery is slipping", "action": "Volume hasn't changed but delivery is slipping — check with production planning whether capacity or materials are the bottleneck; this one's on us"},
        },
        "O": {
            "odm": {"title": "On-time delivery is only fluctuating slightly", "action": "Keep it up — this is the basis for repeat orders"},
            "standard": {"title": "On-time delivery is only fluctuating slightly", "action": "Keep it up — this is the basis for repeat orders"},
        },
        "NA": {
            "odm": {
                "title": "No data for the same period last year, nothing to compare",
                "action": "",
            },
            "standard": {
                "title": "No data for the same period last year, nothing to compare",
                "action": "",
            },
        },
    },
}

ORDERS_REVENUE_TITLES = {
    "zh-TW": {
        "B": {
            ("down", "up"): "訂單筆數變少，但總營收反而成長",
            ("down", "flat"): "訂單筆數變少，總營收大致持平",
            ("down", "down"): "訂單和營收都在掉，營收掉得比較少",
            ("flat", "up"): "訂單筆數差不多，總營收在成長",
            ("up", "up"): "訂單和營收都在成長，營收成長得更快",
        },
        "A": {
            ("up", "down"): "訂單筆數變多，但總營收反而下滑",
            ("up", "flat"): "訂單筆數變多，但總營收沒跟上",
            ("up", "up"): "訂單和營收都在成長，但營收成長得比較慢",
            ("flat", "down"): "訂單筆數差不多，但總營收在下滑",
            ("down", "down"): "訂單和營收都在掉，營收掉得更多",
        },
    },
    "en": {
        "B": {
            ("down", "up"): "Order count is down, but total revenue grew instead",
            ("down", "flat"): "Order count is down, total revenue is roughly flat",
            ("down", "down"): "Both orders and revenue are down, but revenue less so",
            ("flat", "up"): "Order count is roughly flat, total revenue is growing",
            ("up", "up"): "Both orders and revenue are growing, revenue growing faster",
        },
        "A": {
            ("up", "down"): "Order count is up, but total revenue dropped instead",
            ("up", "flat"): "Order count is up, but total revenue hasn't kept pace",
            ("up", "up"): "Both orders and revenue are growing, but revenue growing slower",
            ("flat", "down"): "Order count is roughly flat, but total revenue is dropping",
            ("down", "down"): "Both orders and revenue are down, revenue down more",
        },
    },
}

ORDERS_SHIPMENTS_TITLES = {
    "zh-TW": {
        "H": {
            "odm": {"*": "訂單和出貨一起在成長"},
            "standard": {"*": "訂單和出貨一起在成長"},
        },
        "I": {
            "odm": {"*": "訂單和出貨一起在掉"},
            "standard": {"*": "訂單和出貨一起在掉"},
        },
        "E": {
            "odm": {
                ("up", "down"): "訂單堆著出不掉",
                ("flat", "down"): "訂單差不多，但出貨在掉",
                ("up", "flat"): "訂單變多，出貨沒跟上",
                ("up", "up"): "訂單和出貨都在成長，但出貨跟不上",
                ("down", "down"): "訂單和出貨都在掉，出貨掉得更多",
            },
            "standard": {
                ("up", "down"): "訂單堆著出不掉",
                ("flat", "down"): "訂單差不多，但出貨在掉",
                ("up", "flat"): "訂單變多，出貨沒跟上",
                ("up", "up"): "訂單和出貨都在成長，但出貨跟不上",
                ("down", "down"): "訂單和出貨都在掉，出貨掉得更多",
            },
        },
        "F": {
            "standard": {
                ("down", "up"): "在吃舊訂單，新單沒補上",
                ("down", "flat"): "在吃舊訂單，新單沒補上",
                ("down", "down"): "在吃舊訂單，新單沒補上",
                ("flat", "up"): "訂單差不多，出貨在成長",
                ("up", "up"): "訂單在成長，出貨成長得更快",
            },
            "odm": {
                ("down", "up"): "先前接的單正在大量出貨",
                ("flat", "up"): "先前接的單正在大量出貨",
                ("down", "flat"): "先前接的單還在出，新單變少了",
                ("down", "down"): "訂單和出貨都在掉，出貨掉得比較少",
                ("up", "up"): "訂單在成長，出貨成長得更快",
            },
        },
    },
    "en": {
        "H": {
            "odm": {"*": "Orders and shipments growing together"},
            "standard": {"*": "Orders and shipments growing together"},
        },
        "I": {
            "odm": {"*": "Orders and shipments declining together"},
            "standard": {"*": "Orders and shipments declining together"},
        },
        "E": {
            "odm": {
                ("up", "down"): "Orders are piling up and not shipping",
                ("flat", "down"): "Order count is roughly flat, but shipments are dropping",
                ("up", "flat"): "Order count is up, but shipments haven't kept pace",
                ("up", "up"): "Both orders and shipments are growing, but shipments can't keep up",
                ("down", "down"): "Both orders and shipments are down, shipments down more",
            },
            "standard": {
                ("up", "down"): "Orders are piling up and not shipping",
                ("flat", "down"): "Order count is roughly flat, but shipments are dropping",
                ("up", "flat"): "Order count is up, but shipments haven't kept pace",
                ("up", "up"): "Both orders and shipments are growing, but shipments can't keep up",
                ("down", "down"): "Both orders and shipments are down, shipments down more",
            },
        },
        "F": {
            "standard": {
                ("down", "up"): "Working through backlog, with no new orders replacing it",
                ("down", "flat"): "Working through backlog, with no new orders replacing it",
                ("down", "down"): "Working through backlog, with no new orders replacing it",
                ("flat", "up"): "Order count is roughly flat, shipments are growing",
                ("up", "up"): "Order count is growing, shipments growing even faster",
            },
            "odm": {
                ("down", "up"): "Previously booked orders are shipping in volume",
                ("flat", "up"): "Previously booked orders are shipping in volume",
                ("down", "flat"): "Previously booked orders are still shipping, but new orders have slowed",
                ("down", "down"): "Both orders and shipments are down, shipments down less",
                ("up", "up"): "Order count is growing, shipments growing even faster",
            },
        },
    },
}

ORDERS_SHIPMENTS_ACTIONS = {
    "zh-TW": {
        "H": {
            "odm": "把手上訂單的交期排給生管看，確認產能跟得上",
            "standard": "把手上訂單的交期排給生管看，確認供貨跟得上",
        },
        "I": {
            "odm": "讓生管知道出貨量在縮，別再照舊量備料",
            "standard": "讓生管知道出貨量在縮，別再照舊量備料",
        },
    },
    "en": {
        "H": {
            "odm": "Share the order delivery schedule with production and confirm capacity can keep up",
            "standard": "Share the order delivery schedule with production and confirm supply can keep up",
        },
        "I": {
            "odm": "Let production know shipment volume is shrinking, so they don't over-stock materials",
            "standard": "Let production know shipment volume is shrinking, so they don't over-stock materials",
        },
    },
}

CLUE_QUESTIONS = {
    "zh-TW": {
        "pipeline_vs_orders": [
            {"id": "meaning", "text": "接下來半年會進來多少？"},
            {"id": "conversion", "text": "這些商機有多少會真的變成訂單？"},
        ],
        "won_vs_lost": [
            {"id": "deal_size", "text": "輸掉的是大案還是小案？"},
            {"id": "loss_reasons", "text": "都輸在同一件事上嗎？"},
        ],
        "orders_vs_shipments": [
            {"id": "meaning", "text": "這對後續出貨代表什麼？"},
            {"id": "since_when", "text": "這是一直這樣，還是最近才發生的？"},
        ],
        "orders_vs_revenue": [
            {"id": "aov_driver", "text": "每張單變大（或變小），是買得多、買得貴，還是買的機種換了？"},
            {"id": "margin", "text": "毛利有跟著變嗎？"},
        ],
        "orders_vs_ontime": [
            {"id": "late_count", "text": "實際晚了幾筆、晚多久？"},
            {"id": "late_revenue", "text": "晚交對業績有什麼影響？"},
        ],
    },
    "en": {
        "pipeline_vs_orders": [
            {"id": "meaning", "text": "How much will come in over the next six months?"},
            {"id": "conversion", "text": "How much of this pipeline will actually turn into orders?"},
        ],
        "won_vs_lost": [
            {"id": "deal_size", "text": "Are we losing the big deals or the small ones?"},
            {"id": "loss_reasons", "text": "Do the losses share one cause?"},
        ],
        "orders_vs_shipments": [
            {"id": "meaning", "text": "What does this mean for future shipments?"},
            {"id": "since_when", "text": "Has this always been the case, or is it recent?"},
        ],
        "orders_vs_revenue": [
            {"id": "aov_driver", "text": "Are orders bigger because they buy more, pay more, or buy different models?"},
            {"id": "margin", "text": "Did the margin move with it?"},
        ],
        "orders_vs_ontime": [
            {"id": "late_count", "text": "How many orders were late, and by how much?"},
            {"id": "late_revenue", "text": "What did the late deliveries do to revenue timing?"},
        ],
    },
}

PHASE_LABELS = {
    "zh-TW": {
        "Feasibility evaluation": "初評階段",
        "Proposal": "報價階段",
        "Sampling": "送樣階段",
        "Close": "結案階段",
    },
    "en": {
        "Feasibility evaluation": "Feasibility stage",
        "Proposal": "Proposal stage",
        "Sampling": "Sampling stage",
        "Close": "Closing stage",
    },
}

def phase_label(lang, phase):
    labels = PHASE_LABELS.get(lang, PHASE_LABELS[DEFAULT_LANG])
    if phase in labels:
        return labels[phase]
    if phase:
        return phase
    return "Uncategorized stage" if lang == "en" else "未分類階段"

SCORECARD_GAP_DISPLAY = {
    "zh-TW": {
        "S0": "營收沒有目標可比",
        "S1": "兩項都達標",
        "S2": "一項達標、一項沒達標",
        "S3": "一項達標、一項沒達標",
        "S4": "兩項都沒達標",
    },
    "en": {
        "S0": "No revenue target to compare",
        "S1": "Both targets met",
        "S2": "One target met, one missed",
        "S3": "One target met, one missed",
        "S4": "Both targets missed",
    },
}

CHAIN_LABELS = {
    "zh-TW": {
        "orders_count": "訂單筆數",
        "revenue": "營收",
        "shipments_count": "出貨單數",
        "ontime_rate": "準交率",
        "pipeline_6m": "未來 6 個月商機",
        "orders_6m": "近 6 個月訂單",
        "won": "贏到的案子",
        "lost": "輸掉的案子",
        "revenue_achievement": "營收達成率",
        "gross_margin": "毛利率",
        "hit": "達成目標",
        "not_hit": "未達目標",
        "revenue_ttm": "今年營收",
        "no_target": "新客戶，沒有目標可比",
        "avg_order_value": "每張單平均金額",
    },
    "en": {
        "orders_count": "Order count",
        "revenue": "Revenue",
        "shipments_count": "Shipment count",
        "ontime_rate": "On-time rate",
        "pipeline_6m": "Pipeline (next 6mo)",
        "orders_6m": "Orders (last 6mo)",
        "won": "Deals won",
        "lost": "Deals lost",
        "revenue_achievement": "Revenue achievement",
        "gross_margin": "Gross margin",
        "hit": "Target met",
        "not_hit": "Target missed",
        "revenue_ttm": "Revenue this year",
        "no_target": "New customer, no target yet",
        "avg_order_value": "Avg. order size",
    },
}

PERIOD_LABELS = {
    "zh-TW": {"prev": "去年同期", "cur": "今年"},
    "en": {"prev": "Last year", "cur": "This year"},
}

def _points(pp):
    return "1 point" if float(pp) == 1 else f"{pp} points"

def gap_pp_sentence(lang, faster_label, pp):
    if lang == "en":
        return f"{faster_label} is ahead by {_points(pp)}"
    return f"{faster_label}快 {pp} 個百分點"

def ontime_flat_sentence(lang):
    return "On-time rate is unchanged from last year" if lang == "en" else "準交率跟去年一樣"

def ontime_worse_sentence(lang, pp):
    return f"On-time rate dropped {_points(pp)}" if lang == "en" else f"準交率掉了 {pp} 個百分點"

def ontime_better_sentence(lang, pp):
    return f"On-time rate improved {_points(pp)}" if lang == "en" else f"準交率進步了 {pp} 個百分點"

def ontime_move_display(lang, prev_display, cur_display, pct_display):
    if lang == "en":
        return f"{prev_display} → {cur_display} ({pct_display})"
    return f"{prev_display} → {cur_display}（{pct_display}）"

def revenue_detail_sentence(lang, cur_display, target_display):
    if lang == "en":
        return f"This year {cur_display}, target {target_display}"
    return f"今年 {cur_display}，目標 {target_display}"

def margin_gap_sentence(lang, hit, abs_diff):
    if lang == "en":
        return f"{_points(abs_diff)} above target" if hit else f"{_points(abs_diff)} below target"
    return f"高出 {abs_diff} 個百分點" if hit else f"差 {abs_diff} 個百分點"

def margin_target_caption(lang, target_display):
    return f"Target {target_display}" if lang == "en" else f"目標 {target_display}"

def revenue_achievement_display(lang, revenue_detail, achievement_pct):
    if lang == "en":
        return f"{revenue_detail}, {achievement_pct}% achieved"
    return f"{revenue_detail}，達成 {achievement_pct}%"

def margin_display_sentence(lang, margin_actual_display, margin_target_display, margin_detail):
    if lang == "en":
        return f"{margin_actual_display} (target {margin_target_display}), {margin_detail}"
    return f"{margin_actual_display}（目標 {margin_target_display}），{margin_detail}"

def pipeline_ratio_sentence(lang, ratio):
    return f"{ratio}x recent orders" if lang == "en" else f"是近期訂單的 {ratio} 倍"

def ratio_multiplier_display(lang, ratio):
    return f"{ratio}x" if lang == "en" else f"{ratio} 倍"

def days_open_display(lang, days):
    if days is None:
        return "Not started yet" if lang == "en" else "尚未開始"
    if lang == "en":
        unit = "day" if days == 1 else "days"
        return f"{days} {unit}"
    return f"{days} 天"

_COUNT_UNIT_EN = {"orders": "order", "shipments": "shipment"}

def count_display(lang, n, kind):
    if n is None:
        return "—"
    if lang == "en":
        unit = _COUNT_UNIT_EN.get(kind, kind)
        return f"{n:,} {unit}" if n == 1 else f"{n:,} {unit}s"
    return f"{n:,} 筆"

def lost_count_vs_amount_sentence(lang, lost_n, count_pct, amount_pct):
    if lang == "en":
        noun = "deal" if lost_n == 1 else "deals"
        return f"{lost_n} {noun} lost ({count_pct}% of deals), {amount_pct}% of value"
    return f"輸掉 {lost_n} 件（佔件數 {count_pct}%），金額佔 {amount_pct}%"

def won_lost_chart_note(lang):
    if lang == "en":
        return "Opportunity value closed over the last 2 years — not revenue"
    return "近兩年結案商機的預期金額，不是營收"

UNKNOWN_REASON_DOMINANT_RATIO = 0.5

def unrecorded_reason_action(lang):
    if lang == "en":
        return ("Half or more of the lost deals have no reason recorded — "
                "get the loss reasons filled in before reading into this")
    return "一半以上的輸單系統沒記原因，先把敗因補齊再談"

def tied_reason_action(lang):
    if lang == "en":
        return "No single loss reason dominates — go case by case and find one thing to fix before the next deal"
    return "敗因分散，逐案看輸單，找出下一案能先補的一點"

def customer_type_summary_sentence(lang, type_label, odm_share_pct):
    if lang == "en":
        return f"{type_label}, ODM accounts for {odm_share_pct}% of revenue"
    return f"{type_label}，ODM 佔營收 {odm_share_pct}%"

def facts_line_sentence(lang, left_label, left_display, right_label, right_display, gap_display):
    if lang == "en":
        return f"{left_label}: {left_display}, {right_label}: {right_display}, {gap_display}"
    return f"{left_label} {left_display}，{right_label} {right_display}，{gap_display}"

METRIC_LABEL = {
    "zh-TW": {
        "DOA": "DOA 率",
        "RMA": "RMA 率",
        "CFQR": "CFQR 件數",
        "FPY": "FPY",
        "Repair": "維修率",
    },
    "en": {
        "DOA": "DOA rate",
        "RMA": "RMA rate",
        "CFQR": "CFQR count",
        "FPY": "FPY",
        "Repair": "Repair rate",
    },
}

EXCLUDED_NOTE = {
    "zh-TW": "出貨量未滿 1000 台的客戶不列入氣泡圖（單一案件就會大幅拉動比率）",
    "en": "Customers with under 1,000 units shipped are excluded from the bubble chart (a single case would skew the ratio significantly)",
}

def count_unit(lang, n):
    if lang == "en":
        return f"{n} case" if n == 1 else f"{n} cases"
    return f"{n} 件"
