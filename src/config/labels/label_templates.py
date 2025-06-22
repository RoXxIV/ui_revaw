"""
Templates ZPL pour les étiquettes d'impression.
"""


class LabelTemplates:
    """
    Classe contenant tous les templates ZPL pour les différents types d'étiquettes.
    """

    @staticmethod
    def get_main_label_zpl(serial_number, random_code_for_qr):
        """
        Template ZPL pour l'étiquette principale avec QR code.
        
        Args:
            serial_number (str): Numéro de série de la batterie
            random_code_for_qr (str): Code aléatoire pour le QR code
            
        Returns:
            str: Commande ZPL formatée
        """
        return f"""
   ^XA
    ~TA000
    ~JSN
    ^LT0
    ^MNW
    ^MTT
    ^PON
    ^PMN
    ^LH0,0
    ^JMA
    ^PR4,4
    ~SD15
    ^JUS
    ^LRN
    ^CI27
    ^PA0,1,1,0
    ^XZ
    ^XA
    ^MMT
    ^PW815
    ^LL408
    ^LS0
    ^FT28,33^A0N,14,15^FH\\^CI28^FDModèle : RW-48V27113^FS^CI27
    ^FT28,62^A0N,14,15^FH\\^CI28^FDCapacité : 271 Ah (13 KWh) | Tension nominale : 48 V^FS^CI27
    ^FT28,91^A0N,14,15^FH\\^CI28^FDPlage de tension : 41V - 53V^FS^CI27
    ^FT28,120^A0N,14,15^FH\\^CI28^FDLiFePO4 | Poids : 115 kg | 608*460*248mm^FS^CI27
    ^FPH,2^FT401,39^A0N,20,20^FH\\^CI28^FDAVERTISSEMENT^FS^CI27
    ^FT401,67^A0N,14,15^FH\\^CI28^FDBatterie LiFePO4 – Lire le manuel avant utilisation.^FS^CI27
    ^FT401,98^A0N,17,18^FH\\^CI28^FD-Stockage et manipulation^FS^CI27
    ^FT408,121^A0N,14,15^FH\\^CI28^FDTempérature conseillée : 10°C à 35°C.^FS^CI27
    ^FT408,139^A0N,14,15^FH\\^CI28^FDStocker au sec, à l’abri de la chaleur et de l’humidité.^FS^CI27
    ^FT408,157^A0N,14,15^FH\\^CI28^FDRecharge complète tous les 6 mois et lors du stockage,^FS^CI27
    ^FT408,175^A0N,14,15^FH\\^CI28^FDpositionner l'interupteur arrière sur 0.^FS^CI27
    ^FT401,203^A0N,17,18^FH\\^CI28^FD-Utilisation et sécurité^FS^CI27
    ^FT408,223^A0N,14,15^FH\\^CI28^FDNe pas démonter – Risque d’électrocution/incendie.^FS^CI27
    ^FT408,241^A0N,14,15^FH\\^CI28^FDUtiliser un chargeur compatible LiFePO4.^FS^CI27
    ^FT408,259^A0N,14,15^FH\\^CI28^FDÉviter les courts-circuits et protéger des chocs/vibrations.^FS^CI27
    ^FT401,287^A0N,17,18^FH\\^CI28^FD-Transport et recyclage^FS^CI27
    ^FT408,311^A0N,14,15^FH\\^CI28^FDConforme UN38.3 / UN3480.^FS^CI27
    ^FT408,329^A0N,14,15^FH\\^CI28^FDNe pas jeter – Recycler dans un centre agréé.^FS^CI27
    ^FT408,347^A0N,14,15^FH\\^CI28^FDEn cas de fuite, ne pas toucher, contacter un professionnel.^FS^CI27
    ^FT408,365^A0N,14,15^FH\\^CI28^FDSurchauffe, fumée ou odeur anormale ? ^FS^CI27
    ^FT408,383^A0N,14,15^FH\\^CI28^FDÉloigner immédiatement et contacter les urgences.^FS^CI27
    ^FO249,199^GFA,317,1040,16,:Z64:eJyVkz0OgzAMhR0xROrC2JGjcLT0ZnCFDt05AiMDwk2wnZhHl07vPX0SMf4hoge/iKoQRTGRJdIoeVIe0gkCK+/5BCrVDMZHyaPxJCYZZ8kq5bufJkQdH05KWauT8tzipLzrJb97eMlm95LNJlVsmtPqJYPFSwaz5PnCg2U1NXfyV501N7CXO+9Y/9L44aUa5DG37ywktjz/5PuV98J7y8j//r5mqLfVz17+70/tr3Lsvw0G5uPmB/PF+Q+4H7A/uF+4f7ifuL95sd9N6Lb/t/vA+4lwX3h/QUy9TzvcCe77afxy/1+76fN5:DE32
    ^FO257,278^GFA,233,200,5,:Z64:eJw1jrEKwkAMQN/ZoxwdygkKLkLRXRwFlwp276C7o2NnFw8c7OQ3FCc/wUHwPqVjP8HJmhtckpfkkcQlrhn40a7U7YOkzizarvv+25liW/gUjNOgiBypUx4pvBA5Uzj2TyjPXqx3DVoB94vQRjSym5FYBvoEqv6kwnQepjEWFrJbstCKTpQgtizFkV7U8JLz7IgzrvKcGjIxycnZ8b7KD4ZZlss6+wMAZiRK:2D71
    ^FO305,274^GFA,257,336,8,:Z64:eJwtjz0OwjAMhcOP6IKSI+Qo5hKcx505ReeeAImlG9fo2DEIBoOiGj83kaJPr47f6wvhNvbBzu6pzu7d+NIJTF+dwVw30qqrs3IFVVRALlRcN3LJTprJ97rpegEP5u4BFml3HPqQLCjbo2xMtoQgLKtdEkQgHpaI377xp81+TdssC+LMAzSvrjjPCX59OHqdxz2Og81IMgpGFQJPXAnF99D4PxbWrR97X5t7XxZynSW7jktctjru/wdD2Wg/:36B9
    ^FT246,345^A0N,14,15^FH\\^CI28^FDREVAW^FS^CI27
    ^FT246,365^A0N,14,15^FH\\^CI28^FDwww.revaw.fr^FS^CI27
    ^FT246,383^A0N,14,15^FH\\^CI28^FD^FS^CI27
    ^FT28,171^A0N,14,15^FH\\^CI28^FDNumero de serie : {serial_number}^FS^CI27
    ^FT28,403^BQN,2,7
    ^FH\\^FDLA,https://www.revaw.fr/passport/{serial_number}/{random_code_for_qr}^FS
    ^PQ1,0,1,Y
    ^XZ
    """

    @staticmethod
    def get_v1_label_zpl(serial_number, random_code_for_qr, fabrication_date_str):
        """
        Template ZPL pour l'étiquette V1 (interieur batterie) avec date de fabrication.
        
        Args:
            serial_number (str): Numéro de série de la batterie
            random_code_for_qr (str): Code aléatoire pour le QR code  
            fabrication_date_str (str): Date de fabrication formatée
            
        Returns:
            str: Commande ZPL formatée
        """
        return f"""
      ^XA
~TA000
~JSN
^LT0
^MNW
^MTT
^PON
^PMN
^LH0,0
^JMA
^PR4,4
~SD15
^JUS
^LRN
^CI27
^PA0,1,1,0
^XZ
^XA
^MMT
^PW815
^LL400
^LS0
^FT202,73^A0N,28,28^FH\\^CI28^FDNumero de serie : {serial_number}^FS^CI27
^FT267,348^A0N,28,28^FH\\^CI28^FDFabriqué le : {fabrication_date_str}^FS^CI27
^FT11,36^A0N,28,28^FH\\^CI28^FDV1^FS^CI27
^FT306,322^BQN,2,7
^FH\\^FDLA,{serial_number}^FS
^PQ1,0,1,Y
^XZ
    """

    @staticmethod
    def get_shipping_label_zpl(serial_number):
        """
        Template ZPL pour l'étiquette d'expédition (carton).
        
        Args:
            serial_number (str): Numéro de série de la batterie
            
        Returns:
            str: Commande ZPL formatée
        """
        return f"""
^XA
~TA000
~JSN
^LT0
^MNW
^MTT
^PON
^PMN
^LH0,0
^JMA
^PR4,4
~SD15
^JUS
^LRN
^CI27
^PA0,1,1,0
^XZ
^XA
^MMT
^PW815
^LL400
^LS0
^FT40,343^A0N,45,46^FH\\^CI28^FD{serial_number} - V1^FS^CI27
^FT40,67^A0N,28,28^FH\\^CI28^FDNe pas stocker en exterieur.^FS^CI27
^FT40,115^A0N,28,28^FH\\^CI28^FD48V 271Ah 13KWh^FS^CI27
^FT40,164^A0N,28,28^FH\\^CI28^FD115 kg | 610*460*250mm^FS^CI27
^FO444,39
^BQN,2,10
^FH\\^FDLA,{serial_number}^FS
^PQ1,0,1,Y
^XZ
"""
