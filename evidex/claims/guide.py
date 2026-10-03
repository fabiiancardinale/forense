"""Guía para el liquidador: por qué importa cada tipo de hallazgo y qué hacer con él.

Se muestra debajo de cada alerta en el informe. Está escrita para alguien que no es experto
en informática forense: explica la señal en palabras simples y propone el siguiente paso.
"""
from __future__ import annotations

GUIDE: dict[str, tuple[str, str]] = {
    # ---- fotos: metadatos ------------------------------------------------------------------
    "no_metadata": (
        "Toda foto tomada con un celular guarda dentro del archivo la fecha, la hora, el modelo del teléfono y, a veces, "
        "el lugar. Esta no trae nada de eso. Pasa cuando la foto se reenvió por WhatsApp o redes sociales (que borran "
        "esos datos), cuando es una captura de pantalla o cuando se descargó de internet. No prueba fraude, pero impide "
        "confirmar que la foto sea de este choque.",
        "Pida al asegurado la foto original desde la galería de su teléfono, usando el enlace del portal (no por "
        "WhatsApp). Si dice no tenerla, pregúntele quién la tomó y cuándo."),
    "edited": (
        "El archivo dice que pasó por un programa de edición de imágenes. Editar puede ser inocente (recortar, aclarar), "
        "pero también permite agregar o agrandar un daño.",
        "Compare la foto con las demás del mismo daño y pida el original sin editar."),
    "ai_generated": (
        "La imagen tiene marcas que dejan los programas que crean imágenes con inteligencia artificial. Una foto real "
        "de un choque no debería tenerlas.",
        "Trátela como no válida. Pida fotos nuevas por el portal o una inspección presencial del vehículo."),
    "taken_before": (
        "La fecha guardada en la foto es anterior al choque declarado: el daño ya existía antes, o la foto es de otro "
        "evento.",
        "Pregunte al asegurado cuándo y dónde tomó la foto. Revise si hay un siniestro anterior del mismo vehículo."),
    "taken_late": (
        "La foto se tomó muchos días después del choque. Puede ser normal (fotos para el taller), pero el daño pudo "
        "cambiar o agrandarse en ese tiempo.",
        "Pida fotos del día del choque, si existen, y compárelas."),
    "gps_mismatch": (
        "La foto guarda la ubicación donde se tomó, y está lejos del lugar donde se declaró el choque.",
        "Pregunte por qué la foto se tomó en ese lugar (taller, casa). Si dice que fue en el lugar del choque, hay una "
        "contradicción que investigar."),
    "reused_photo": (
        "Esta misma foto, o una casi igual (recortada o con otro tamaño), ya se presentó en otro siniestro. Una foto real "
        "de un choque no se repite en otro reclamo.",
        "Derive a investigación y revise el otro siniestro: puede ser una red que recicla fotos."),
    "exif_dates_mismatch": (
        "Dentro de la foto hay varias fechas que una cámara escribe iguales, y aquí no coinciden. Indica que alguien "
        "cambió la fecha a mano.",
        "Pida el archivo original y pregunte cuándo se tomó realmente la foto."),
    "exif_gps_time_mismatch": (
        "El GPS del teléfono registra su propia hora, y no calza con la fecha de la foto. Es la huella típica de una "
        "fecha cambiada a mano.",
        "Considere la fecha de la foto como no confiable y pida el original."),
    "exif_resaved": (
        "El archivo se volvió a guardar después de tomada la foto. Puede ser un programa que copió las fotos o una "
        "edición.",
        "Si la foto es importante para la decisión, pida el original."),
    "thumbnail_mismatch": (
        "La foto guarda dentro una miniatura de cómo era originalmente, y esa miniatura muestra otra imagen. Alguien "
        "editó la foto conservando los datos del original.",
        "Trátela como editada. Pida el original o una inspección del vehículo."),
    "exif_no_exposure": (
        "La foto dice venir de una cámara, pero le faltan datos que toda cámara registra. Suele ocurrir cuando se "
        "agregan datos falsos a una imagen que no salió de esa cámara.",
        "Pida el original desde la galería del teléfono."),
    "metadata_tool": (
        "El archivo tiene rastros de programas que sirven para cambiar la fecha, la cámara o la ubicación de una foto.",
        "Considere la fecha y el lugar de la foto como no confiables."),
    "taken_future": (
        "La foto dice haberse tomado después de que la recibimos, lo que es imposible. La fecha se cambió o el reloj "
        "del teléfono estaba mal.",
        "No use la fecha de esta foto como prueba."),
    "screenshot": (
        "Es una captura de pantalla, no una foto tomada con la cámara. Un pantallazo no prueba cuándo ni dónde se tomó "
        "la imagen original, y puede ser de una foto ajena.",
        "Pida la foto original."),
    # ---- fotos: contenido ------------------------------------------------------------------
    "pasted_region": (
        "Una zona de la foto se guardó de forma distinta al resto, como si se hubiera pegado desde otra imagen (un daño, "
        "una patente, un objeto). La zona está marcada en rojo en Revisar foto.",
        "Revise la zona marcada y pida una inspección presencial del daño."),
    "recompressed": (
        "La foto dice venir directo de la cámara, pero se abrió y guardó de nuevo, por ejemplo en un editor.",
        "Pida el original y compárelo."),
    "cloned_region": (
        "Una parte de la foto está copiada en otro lugar de la misma imagen. Se usa para agrandar un daño o tapar algo.",
        "Pida una inspección presencial del vehículo."),
    "daylight_at_night": (
        "La foto muestra cielo de día, pero su fecha dice que se tomó de noche en ese lugar. La fecha de la foto no es "
        "la real.",
        "No use la fecha de esta foto como prueba y pregunte cuándo se tomó."),
    "c2pa_invalid": (
        "La foto traía una firma digital de autenticidad de la cámara, y la firma está rota: se modificó después de "
        "tomada.",
        "Trátela como editada y pida el original."),
    "plate_photo_mismatch": (
        "Evidex lee las patentes que aparecen en las fotos y las compara con la del vehículo asegurado. En esta foto "
        "se lee otra patente.",
        "Mire la foto: si es el otro auto del choque o uno que pasaba, no hay problema. Si es la foto que debía mostrar "
        "el vehículo asegurado, es una foto de otro auto y corresponde investigar."),
    "noise_inconsistent": (
        "Toda la foto sale del mismo sensor, así que el \"grano\" de la imagen debería ser parejo (según la luz). "
        "Una zona con un grano claramente distinto puede haberse pegado desde otra foto o retocado. Es una señal de "
        "apoyo: por sí sola no prueba edición.",
        "Mire la zona marcada en morado en Revisar foto (y el mapa de ruido). Si coincide con el daño, pida una "
        "inspección presencial."),
    "resized_after_capture": (
        "La cámara anota dentro del archivo el tamaño exacto de la foto que guardó. Si el archivo mide otra cosa, la foto "
        "se recortó o se achicó después. Recortar permite sacar del cuadro algo que contradice el relato (la patente, "
        "otro auto, el lugar).",
        "Pida al asegurado la foto original, completa, desde la galería de su teléfono por el portal."),
    "makernote_missing": (
        "Todo iPhone guarda en la foto una \"nota del fabricante\" con datos técnicos. Si la foto dice ser de iPhone "
        "y no la tiene, los metadatos se copiaron de otra foto o se escribieron con un programa.",
        "Considere la fecha y el lugar de la foto como no confiables y pida el original."),
    "ai_dimensions": (
        "Los generadores de imágenes con IA producen tamaños fijos (1024×1024, 1344×768…) que ninguna cámara de teléfono "
        "usa, y no agregan datos de cámara.",
        "Pida fotos nuevas tomadas con la cámara del portal, o una inspección presencial."),
    "edit_filename": (
        "El nombre del archivo es el que dejan las apps de edición o las copias (\"editado\", \"copia\", \"(1)\").",
        "Pida la foto original desde la galería."),
    "saved_before_taken": (
        "El teléfono informa cuándo se guardó el archivo. Si ese momento es anterior a la fecha que dice la foto, la "
        "fecha de la foto se cambió a mano.",
        "No use la fecha de esta foto como prueba y pregunte al asegurado cuándo la tomó."),
    "same_device_other_claim": (
        "Algunas cámaras graban su número de serie en cada foto. La misma cámara aparece en el siniestro de otro "
        "asegurado: la misma persona fotografió ambos choques.",
        "Revise el otro siniestro y quién tomó las fotos (taller, tramitador). Derive a investigación."),
    "mirrored_in_claim": (
        "Una foto es la otra invertida de izquierda a derecha. Se usa para presentar un mismo daño como si fueran dos "
        "(por ejemplo, ambos costados del auto).",
        "Trátela como fraude probable: derive a investigación y pida inspección presencial."),
    "duplicate_in_claim": (
        "Dos fotos del siniestro son prácticamente la misma imagen.",
        "Si se presentaron como daños distintos, pregunte al asegurado; si es una ráfaga, no hay problema."),
    "multiple_devices": (
        "Las fotos se tomaron con cámaras distintas. Es normal si una la tomó el otro conductor o la grúa, pero no si "
        "el asegurado dice haberlas tomado todas él.",
        "Pregunte quién tomó cada foto. Si alguna no tiene explicación, puede ser de otro evento."),
    "ai_detected": (
        "Un servicio externo de detección estima que la imagen fue creada o modificada con inteligencia artificial.",
        "Pida fotos nuevas por el portal o una inspección presencial."),
    "found_online": (
        "La misma foto está publicada en internet. Una foto propia del choque no debería estar en otros sitios.",
        "Revise el sitio donde aparece y derive a investigación."),
    "capture_no_gps": (
        "La foto se tomó con la cámara del portal, pero el asegurado no permitió registrar la ubicación.",
        "Pregúntele dónde estaba al tomarla."),
    # ---- documentos ------------------------------------------------------------------------
    "doc_editor": (
        "El PDF pasó por un programa que permite cambiar su contenido (montos, fechas, nombres).",
        "Pida el documento directamente al emisor (taller, Carabineros, tienda) y compárelo."),
    "doc_modified": (
        "El PDF se modificó después de crearse. Puede ser legítimo (una corrección), pero también un cambio de monto.",
        "Revise la sección Documentos del informe: si hay una versión anterior recuperada, compare qué cambió."),
    "doc_version_changed": (
        "Dentro del PDF quedó guardada su versión anterior, y en ella el monto o la fecha eran otros. Es la prueba de "
        "que alguien cambió el documento.",
        "Descargue ambas versiones desde la sección Documentos y confirme el monto real con el emisor."),
    "doc_version_text": (
        "Dentro del PDF quedó guardada una versión anterior con otro texto.",
        "Compare las versiones en la sección Documentos."),
    "doc_before_claim": (
        "El presupuesto o la factura se creó antes del choque. Un documento de reparación no puede ser anterior al daño.",
        "Confirme la fecha con el taller o la tienda; puede ser de un daño anterior."),
    "doc_dated_before": (
        "La fecha escrita en el documento es anterior al choque declarado.",
        "Confirme la fecha con el emisor del documento."),
    "reused_doc": (
        "El mismo documento, idéntico, ya se presentó en otro siniestro.",
        "Derive a investigación y revise el otro siniestro."),
    "doc_no_metadata": (
        "El PDF no dice cuándo ni con qué programa se creó. Es común en documentos generados por algunos sistemas, pero "
        "impide verificar su origen.",
        "Si el documento es clave para el monto, pídalo al emisor."),
    "not_pdf": (
        "El archivo dice ser PDF pero no lo es.", "Pida el documento de nuevo."),
    "doc_rut_invalid": (
        "El RUT escrito en el documento tiene el dígito verificador incorrecto. Los sistemas de facturación y el SII "
        "lo calculan solos, así que un RUT mal escrito indica un documento hecho o modificado a mano.",
        "Verifique el RUT del emisor en el SII y pida el documento original."),
    "doc_plate_mismatch": (
        "El documento menciona otra patente, no la del vehículo asegurado.",
        "Confirme a qué vehículo corresponde el documento."),
    # ---- datos del asegurado ---------------------------------------------------------------
    "rut_invalid": (
        "El RUT declarado no es válido: el dígito verificador no corresponde.",
        "Corrija el RUT con el asegurado; si insiste en ese número, verifique su identidad."),
    "plate_invalid": (
        "La patente declarada no tiene un formato de patente chilena.",
        "Corrija la patente con el padrón del vehículo."),
    # ---- línea de tiempo ------------------------------------------------------------------
    "impossible_travel": (
        "Dos hechos (fotos, mensajes o el lugar del choque) están demasiado lejos uno del otro para el tiempo que hay "
        "entre ellos. Al menos una de las horas o de los lugares es falso.",
        "Revise la línea de tiempo forense y pregunte al asegurado por cada uno de los dos hechos."),
    "photo_before_policy": (
        "Hay fotos del daño con fecha anterior a la contratación de la póliza: el daño podría ser previo a la cobertura.",
        "Pida la inspección de contratación de la póliza y compare el estado del vehículo."),
    # ---- comunicaciones -------------------------------------------------------------------
    "chat_before_event": (
        "En el chat se habla del choque, del seguro o del presupuesto antes de que ocurriera.",
        "Derive a investigación: puede ser un choque planificado."),
    "chat_script": (
        "Hay mensajes que acuerdan qué decir ('dile que', 'acuérdate que'). Sugiere una versión preparada.",
        "Entreviste por separado a las personas del chat."),
    "chat_deleted": (
        "Se borraron mensajes cerca del siniestro.", "Pregunte qué decían los mensajes eliminados."),
    "chat_phone_link": (
        "El chat menciona un teléfono registrado en otro siniestro de otro asegurado.",
        "Revise el otro siniestro y la red."),
    # ---- red y póliza ---------------------------------------------------------------------
    "shared_contact": (
        "Otro asegurado distinto usa el mismo teléfono, correo, cuenta bancaria o dirección. Es una de las señales más "
        "comunes de redes de fraude.",
        "Revise el otro siniestro y la relación entre ambos asegurados."),
    "fraud_ring": (
        "Este siniestro está conectado con varios otros siniestros de distintos asegurados.",
        "Revise la sección Red de siniestros y derive a investigación."),
    "copied_narrative": (
        "El relato es muy parecido al de otro siniestro. Los relatos reales suelen ser distintos.",
        "Compare ambos relatos y revise si comparten taller o intermediario."),
}


def for_rule(rule: str) -> tuple[str, str] | None:
    return GUIDE.get(rule)
