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
    "ai_label_visible": (
        "En la imagen se lee una marca como «Contenido generado por IA». Samsung, Google, Meta y otras apps la estampan "
        "cuando la foto se creó o se editó con inteligencia artificial.",
        "No acepte la foto como prueba del daño. Pida la foto original sin editar o una inspección presencial."),
    "ai_mark_cropped": (
        "Una foto es otra del mismo caso recortada, y el recorte quitó justo la marca que decía que la imagen se hizo "
        "o editó con IA. Es un intento de ocultar la edición.",
        "Trátela como fraude probable: derive a investigación y pida inspección presencial del vehículo."),
    "changed_between_versions": (
        "Dos fotos del caso son la misma toma, pero en una de ellas una zona cambió: se borró, agregó o cambió algo, "
        "como hacen el borrador mágico o la edición con IA de los teléfonos.",
        "Compare las dos fotos en la zona indicada. Si lo que cambió es parte del daño, derive a investigación."),
    "cropped_in_claim": (
        "Una foto del siniestro es otra foto del mismo caso recortada. Recortar puede ser para encuadrar, pero también "
        "para sacar algo que no convenía mostrar.",
        "Mire en la foto completa qué quedó fuera del recorte. Si se presentaron como fotos distintas, pregunte."),
    "odd_ratio": (
        "La foto no tiene ninguna de las proporciones en que guardan las fotos los teléfonos (4:3, 16:9, 1:1...): "
        "se recortó a mano o se generó.",
        "Pida la foto completa, tal como salió de la cámara (enviada como Documento por WhatsApp o por correo)."),
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
    "ai_edited": (
        "El propio archivo declara que se usó inteligencia artificial: lo anotan el teléfono o la app al guardar "
        "(Galaxy AI de Samsung, las herramientas de IA de Google Fotos, credenciales C2PA, el campo IPTC «tipo de "
        "origen digital»). Basta con usar la IA una vez, aunque el cambio sea pequeño (borrar un objeto, rellenar un "
        "fondo, \"mejorar\" la foto).",
        "Pida la foto original sin editar, por el portal y no por WhatsApp. Compare con las otras fotos del mismo daño y, "
        "si la parte editada puede ser el daño, pida inspección presencial."),
    "ai_watermark_removed": (
        "Las apps que editan con IA ponen una marca visible en la esquina. El editor registró que esa marca se quitó: "
        "alguien no quería que se notara la edición.",
        "Trátela como fraude probable: derive a investigación y pida inspección presencial del vehículo."),
    "copy_of_ai_photo": (
        "Esta foto es la misma imagen (o un recorte) de otra foto que sí declara uso de inteligencia artificial. La copia "
        "perdió las marcas porque pasó por WhatsApp, redes sociales o una captura de pantalla, que las borran.",
        "Trátela igual que la original editada con IA: no la acepte como prueba y pida la foto original o una "
        "inspección presencial."),
    "phone_edit": (
        "El archivo guarda el historial de lo que se le hizo después de tomarlo: recortes, giros, cambios de luz o color, "
        "filtros, o que se creó a partir de otra foto. Puede ser inocente (encuadrar), pero cambia lo que se ve.",
        "Pida la foto original y compare: fíjese en qué quedó fuera del recorte o qué cambió de color o brillo."),
    "meta_dates_conflict": (
        "Una foto guarda su fecha en varias secciones (EXIF, XMP, IPTC y, en Samsung, una hora UTC propia). Deben "
        "coincidir. Cuando alguien cambia la fecha con una app, casi siempre cambia solo una de ellas.",
        "No use la fecha de la foto como prueba. Pregunte cuándo se tomó y pida el original."),
    "copied_narrative": (
        "El relato es muy parecido al de otro siniestro. Los relatos reales suelen ser distintos.",
        "Compare ambos relatos y revise si comparten taller o intermediario."),
}


def for_rule(rule: str) -> tuple[str, str] | None:
    return GUIDE.get(rule)


# Por qué cada alerta tiene el nivel que tiene (alta, media o baja). Se muestra junto a la explicación.
WHY = {
    # IA
    "ai_generated": "Alta porque una imagen hecha con IA no muestra un hecho real: no sirve como prueba del daño.",
    "ai_edited": "Alta porque con IA se puede borrar, agregar o agrandar un daño con un resultado que a la vista parece una "
                 "foto real. Aunque el cambio haya sido pequeño, la foto ya no prueba por sí sola cómo estaba el vehículo.",
    "copy_of_ai_photo": "Alta porque es la misma imagen que una foto editada con IA: perder las marcas al reenviarla "
                        "no cambia lo que muestra.",
    "ai_watermark_removed": "Alta porque quitar la marca de IA es un acto deliberado para ocultar la edición.",
    "ai_label_visible": "Alta porque la propia imagen dice que fue generada o editada con IA.",
    "ai_mark_cropped": "Alta porque recortar justo la marca de IA es un intento de ocultar la edición.",
    "ai_detected": "Alta o media según el puntaje del detector externo: es una estimación, no una prueba.",
    "ai_dimensions": "Media porque el tamaño coincide con generadores de IA, pero por sí solo no lo prueba.",
    # edición
    "phone_edit": "Media porque editar en la galería es común y suele ser inocente (encuadrar, aclarar), pero puede "
                  "sacar del cuadro o disimular algo; no es alta mientras no haya IA ni cambios de contenido.",
    "edited": "Alta porque un editor de imágenes permite cambiar el contenido, no solo el encuadre.",
    "resized_after_capture": "Media porque recortar puede ser inocente, pero también sirve para sacar algo del cuadro.",
    "odd_ratio": "Baja porque un recorte a mano es común; solo indica que falta parte de la foto original.",
    "edit_filename": "Baja porque el nombre del archivo se cambia fácil; solo sugiere que pasó por una app.",
    "recompressed": "Media porque volver a guardar una foto es común, pero borra rastros y puede ocultar ediciones.",
    "changed_between_versions": "Alta porque hay dos versiones de la misma foto y en una cambió el contenido.",
    "cropped_in_claim": "Media porque recortar puede ser inocente, pero hay que ver qué quedó fuera.",
    # píxeles
    "pasted_region": "Alta porque una zona con otra huella de compresión indica que se pegó desde otra imagen.",
    "cloned_region": "Alta porque una parte copiada dentro de la misma foto es una manipulación del contenido.",
    "noise_inconsistent": "Media porque el grano distinto puede venir de una zona pegada, pero también de luz muy dispareja.",
    "daylight_at_night": "Media porque indica que la fecha de la foto no es la real, aunque no prueba el fraude.",
    "c2pa_invalid": "Alta porque la imagen cambió después de que el teléfono o la app la firmó.",
    # metadatos y fechas
    "no_metadata": "Media si la subió el asegurado (no se puede verificar) y baja si llegó por WhatsApp, que borra "
                   "estos datos siempre.",
    "meta_dates_conflict": "Media porque fechas que no calzan indican que una se cambió, pero no dicen cuál es la real.",
    "exif_dates_mismatch": "Alta porque las fechas internas deben coincidir; si no, alguien las cambió.",
    "saved_before_taken": "Alta porque es imposible que el archivo exista antes de tomar la foto: la fecha se cambió.",
    "metadata_tool": "Alta porque esos programas sirven para cambiar fecha, lugar o cámara de una foto.",
    "taken_before": "Alta porque una foto anterior al choque no puede mostrar el daño de este choque.",
    "taken_late": "Media porque fotos tardías pueden ser normales, pero el daño pudo cambiar en ese tiempo.",
    "photo_before_policy": "Alta porque sugiere que el daño existía antes de contratar la póliza.",
    "gps_mismatch": "Alta si está a más de 50 km y media si está más cerca: la foto no es del lugar declarado.",
    "screenshot": "Media porque un pantallazo no trae datos de cámara: no prueba cuándo ni dónde.",
    "makernote_missing": "Media porque a un iPhone no le falta esa sección salvo que el archivo se haya reprocesado.",
    # repetición
    "reused_photo": "Alta porque la misma foto ya se usó en otro siniestro.",
    "mirrored_in_claim": "Alta porque espejar una foto para mostrarla como el otro costado es engañar a propósito.",
    "duplicate_in_claim": "Media porque puede ser una ráfaga; importa si se presentó como daños distintos.",
    "same_device_other_claim": "Alta porque la misma cámara aparece en siniestros de personas distintas.",
    "multiple_devices": "Media porque es normal si otra persona tomó fotos, pero no si el asegurado dice que las tomó él.",
    "found_online": "Alta porque una foto publicada en internet antes del choque no es de este siniestro.",
    "plate_photo_mismatch": "Alta si es la foto de la patente y media si es otra foto: puede ser otro vehículo.",
}
SEVERITY_WHY = {
    "alta": "Alta: si se confirma, la evidencia no prueba lo que se declaró; conviene aclararlo antes de pagar.",
    "media": "Media: puede tener una explicación inocente, pero junto con otras alertas cambia la evaluación; hay que preguntar.",
    "baja": "Baja: por sí sola no indica fraude; se informa para tener el cuadro completo.",
}


def explain(rule: str, severity: str) -> dict:
    """Qué es, por qué ese nivel y qué hacer, para mostrar junto a cada alerta."""
    what, todo = GUIDE.get(rule, ("", ""))
    return {"what": what, "why": WHY.get(rule) or SEVERITY_WHY.get(severity, ""), "todo": todo}
