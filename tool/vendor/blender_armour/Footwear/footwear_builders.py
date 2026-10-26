"""Build physically different footwear rather than recolouring one shoe."""
from footwear_last import sole,upper,laces
from footwear_fittings import ankle_strap
from footwear_plates import plate_foot
from footwear_mail import foot_mail

# //#GPT: Keep a leather walking sole under armour and leave each upper open at the ankle.
def build(kind,p,mats,collection):
    sole(p,mats,collection)
    covered = kind in {"mail_foot","round_sabaton","pointed_sabaton"}
    upper(p,mats,collection,laced=not covered)
    if not covered:
        laces(p,mats,collection)
    if kind=="ankle_boot":
        for i,z in enumerate((0.125,0.168)):
            ankle_strap(p,z,mats,collection,f"Boot_Strap_{i}")
    if kind=="mail_foot":
        foot_mail(p,mats,collection)
        ankle_strap(p,p["shaft_height"]-0.006,mats,collection,"Mail_Binding")
    if kind in {"round_sabaton","pointed_sabaton","hybrid_boot"}:
        plate_foot(p,mats,collection,hybrid=kind=="hybrid_boot")
    if kind=="hybrid_boot":
        foot_mail(p,mats,collection,cuff_only=True)
        ankle_strap(p,p["shaft_height"]-0.007,mats,collection,"Hybrid_Cuff_Strap")
