"""Variant definitions, parameter bounds and centralized review labels."""
import math

VARIANTS = {
    "leather":{"depth":0.042,"point":0.002,"wing_width":0},
    "mail":{"wing_width":0},
    "early_plate":{"point":0.005,"wing_width":0},
    "winged_plate":{"point":0.008,"wing_width":0.038},
    "articulated_plate":{"point":0.006,"wing_width":0.030},
    "plate_mail_hybrid":{"point":0.006,"wing_width":0.028}
}
DEFAULTS = {"half_width":0.057,"half_height":0.065,"depth":0.055,"point":0.005,
            "arm_radius":0.047,"wing_width":0.030,"steel_thickness":0.002,
            "leather_thickness":0.0045,"strap_width":0.014,"segments":96,
            "cup_rings":20,"mail_columns":44,"mail_rows":18,"ring_radius":0.0044}
BOUNDS = {"half_width":(0.047,0.075),"half_height":(0.055,0.080),"depth":(0.035,0.070),
          "point":(0,0.012),"arm_radius":(0.034,0.057),"wing_width":(0,0.055),
          "steel_thickness":(0.0015,0.0035),"leather_thickness":(0.003,0.007),
          "strap_width":(0.011,0.020),"segments":(64,128),"cup_rings":(12,28),
          "mail_columns":(32,56),"mail_rows":(12,20),"ring_radius":(0.0035,0.0052)}
LABELS = {
    "title":"Локтевая защита · шесть конструкций",
    "intro":"Процедурные модели Blender: левый и правый локоть отдельными GLB.",
    "front":"Снаружи","side":"Сбоку","back":"Изнутри · крепления",
    "hero":"Три четверти","inside":"Внутренняя сторона под углом","pair":"Левая и правая",
    "leather":"Кожаный налокотник","mail":"Кольчужный участок рукава",
    "early_plate":"Простая стальная чашка","winged_plate":"Чашка с защитным крылом",
    "articulated_plate":"Чашка с набором пластин","plate_mail_hybrid":"Сталь и кольчужная вставка",
    "leather_note":"Игровая интерпретация формованной кожи; точная историческая форма не подтверждена.",
    "mail_note":"Участок кольчужного рукава, выделенный для модульного набора.",
    "plate_note":"Обобщение конструкции исторического налокотника; без копирования конкретного экспоната.",
    "hybrid_note":"Игровой модуль на основе чашки и кольчужного прикрытия сгиба.",
    "limits":"Нужны подгонка под персонажа и оптимизация. Движение пластин и контакты колец не рассчитаны.",
    "triangles":"треугольников на один локоть","imported":"Проверка GLB после импорта",
    "guide":"Инструкция","evidence":"Проверки","sources":"Источники и допущения",
    "more":"Дополнительные ракурсы","right":"Правый GLB","left":"Левый GLB","blend":"Сцена BLEND"
}

# //#GPT: Bound every numeric input before Blender allocates geometry.
def validate_config(kind,config):
    if kind not in VARIANTS or not isinstance(config,dict):
        raise ValueError("Unsupported elbow construction or invalid configuration")
    if set(config)-set(DEFAULTS):
        raise ValueError("Unknown parameter name")
    p = {**DEFAULTS,**VARIANTS[kind],**config}
    integers = {"segments","cup_rings","mail_columns","mail_rows"}
    for key,value in p.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f"Invalid numeric value: {key}")
        if not BOUNDS[key][0]<=value<=BOUNDS[key][1]:
            raise ValueError(f"Parameter outside supported range: {key}")
        if key in integers and not isinstance(value,int):
            raise ValueError(f"Integer required: {key}")
    if p["segments"]%8:
        raise ValueError("segments must be a multiple of 8")
    if p["half_width"]<p["arm_radius"]*1.06:
        raise ValueError("Cup must be wider than the fastening band")
    if kind in {"leather","mail","early_plate"} and p["wing_width"]!=0:
        raise ValueError("This construction has no lateral wing")
    return p
