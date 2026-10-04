"""Compatibility route for the unified, bounded file inspection flow."""
from flask import Blueprint, redirect, url_for
bp = Blueprint('tools', __name__)
@bp.get('/foto')
def photo_check():
    return redirect(url_for('inspection.index'), code=302)
