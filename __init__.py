# Point d’entrée du plugin QRator

def classFactory(iface):
    from .QRator import QRator
    return QRator(iface)
