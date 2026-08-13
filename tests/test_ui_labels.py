from corredores.services.ui_labels import label_es


def test_label_es_common_statuses():
    assert label_es("ACTIVE") == "Activo"
    assert label_es("INVITED") == "Invitado"
    assert label_es("pending") == "Pendiente"
    assert label_es("UPCOMING") == "Próxima"
    assert label_es("REPORTED") == "Reportado"
    assert label_es("UNKNOWN_CODE_XYZ") == "UNKNOWN_CODE_XYZ"
