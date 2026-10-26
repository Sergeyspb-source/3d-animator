"""Six footwear forms, bounded dimensions and centralized presentation labels."""
import math
VARIANTS = {
    "leather_shoe":{"shaft_height":0.103},
    "ankle_boot":{"shaft_height":0.185},
    "mail_foot":{"shaft_height":0.137},
    "round_sabaton":{"shaft_height":0.110,"toe_extension":0.012},
    "pointed_sabaton":{"shaft_height":0.110,"toe_extension":0.068},
    "hybrid_boot":{"shaft_height":0.165,"toe_extension":0.008}
}
DEFAULTS = {"foot_length":0.270,"foot_width":0.100,"ankle_height":0.085,
            "shaft_height":0.110,"sole_thickness":0.008,"leather_thickness":0.0025,
            "steel_thickness":0.0016,"segments":96,"toe_extension":0,
            "mail_columns":20,"mail_rows":28,"cuff_rows":10,"ring_radius":0.0042}
BOUNDS = {"foot_length":(0.235,0.310),"foot_width":(0.085,0.120),
          "ankle_height":(0.075,0.100),"shaft_height":(0.100,0.210),
          "sole_thickness":(0.006,0.011),"leather_thickness":(0.0018,0.004),
          "steel_thickness":(0.0012,0.0028),"segments":(64,128),
          "toe_extension":(0,0.080),"mail_columns":(16,24),"mail_rows":(22,34),
          "cuff_rows":(7,14),"ring_radius":(0.0035,0.0048)}
LABELS = {
 "title":"Обувь и защита стопы · шесть вариантов","intro":"Левая и правая модели, отдельные GLB и парные сцены Blender.",
 "leather_shoe":"Кожаные башмаки","ankle_boot":"Короткие сапоги","mail_foot":"Кольчужная защита стопы",
 "round_sabaton":"Округлые сабатоны","pointed_sabaton":"Заострённые сабатоны","hybrid_boot":"Кожа, сталь и кольчуга",
 "front":"Спереди","side":"Сбоку","back":"Сзади · крепления","hero":"Три четверти",
 "sole":"Подошва","top":"Сверху · вход для ноги","pair":"Левая и правая",
 "guide":"Инструкция","sources":"Источники и допущения","evidence":"Проверки",
 "more":"Остальные ракурсы","right":"Правый GLB","left":"Левый GLB","blend":"Сцена BLEND",
 "triangles":"треугольников на одну стопу","imported":"GLB после повторного импорта",
 "limits":"Прототипы: нужны подгонка, веса и оптимизация. Движение пластин и физика колец не рассчитаны."
}

# //#GPT: Constrain output size and reject unsupported or non-finite dimensions before building.
def validate_config(kind,config):
    if kind not in VARIANTS or not isinstance(config,dict) or set(config)-set(DEFAULTS):
        raise ValueError("Unsupported variant or parameter")
    p = {**DEFAULTS,**VARIANTS[kind],**config}
    for key,value in p.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f"Invalid numeric value: {key}")
        if not BOUNDS[key][0]<=value<=BOUNDS[key][1]:
            raise ValueError(f"Out of range: {key}")
        if key in {"segments","mail_columns","mail_rows","cuff_rows"} and not isinstance(value,int):
            raise ValueError(f"Integer required: {key}")
    if p["segments"]%8 or p["foot_length"]/p["foot_width"]<2.2:
        raise ValueError("Unsupported proportions or segment count")
    if kind in {"leather_shoe","ankle_boot","mail_foot"} and p["toe_extension"]!=0:
        raise ValueError("Steel toe extension applies only to armoured variants")
    return p
