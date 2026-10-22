from flask import render_template, request, redirect, url_for, flash, make_response

def register_appearance_routes(bp):
    @bp.route('/settings/appearance', methods=['GET', 'POST'])
    def settings_appearance():
        """Manage application UI themes (Appearance)."""
        if request.method == 'POST':
            selected_theme = request.form.get('theme', 'default')
            flash('Appearance theme updated successfully!', 'success')
            response = make_response(redirect(url_for('settings_bp.settings_appearance')))
            response.set_cookie('app_theme', selected_theme, max_age=60*60*24*365)
            return response
            
        current_theme = request.cookies.get('app_theme', 'default')
        return render_template('settings/appearance.html', current_theme=current_theme)