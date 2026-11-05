BOX = "0 0 24 24"

ICON = {
    "wars": '<path d="M12 3 20 6v6c0 5-4 8-8 9-4-1-8-4-8-9V6Z"/>',
    "clan": '<path d="M6 21V4"/>'
            '<path d="M6 5h12l-3 4 3 4H6"/>',
    "me": '<rect x="3" y="4" width="18" height="16" rx="5"/>'
          '<circle cx="12" cy="10" r="2.5"/>'
          '<path d="M7.5 17c1-2.4 2.6-3.4 4.5-3.4s3.5 1 4.5 3.4"/>',
    "more": '<rect x="4" y="4" width="7" height="7" rx="2"/>'
            '<rect x="13" y="4" width="7" height="7" rx="2"/>'
            '<rect x="4" y="13" width="7" height="7" rx="2"/>'
            '<rect x="13" y="13" width="7" height="7" rx="2"/>',
    "manage": '<path d="M4 8h16M4 16h16"/>'
              '<circle cx="9" cy="8" r="2.5"/>'
              '<circle cx="15" cy="16" r="2.5"/>',
    "cwl": '<path d="M5 6 8 15h8l3-9-4 3.5L12 4 8 9.5Z"/>'
           '<path d="M7 19h10"/>',
    "capital_games": '<rect x="3" y="9" width="18" height="10" rx="4"/>'
                     '<path d="M7 14h3M8.5 12.5v3"/>'
                     '<circle cx="16" cy="14" r="1" fill="currentColor" stroke="none"/>',
    "members": '<circle cx="12" cy="9" r="4"/>'
               '<path d="M5 20c1-4 4-6 7-6s6 2 7 6"/>',
    "challenges": '<circle cx="12" cy="9" r="5"/>'
                  '<path d="m9 14-1 7 4-2 4 2-1-7"/>',
    "family": '<circle cx="8" cy="9" r="3"/>'
              '<circle cx="16" cy="9" r="3"/>'
              '<path d="M2 19c1-3 3-4 6-4s5 1 6 4M12 19c1-3 3-4 6-4s4 1 4 4"/>',
    "recruitment": '<circle cx="10" cy="9" r="4"/>'
                   '<path d="M3 20c1-4 4-6 7-6"/>'
                   '<path d="M17 14v7M13.5 17.5h7"/>',
    "bases": '<path d="M4 20V10l8-6 8 6v10Z"/>'
             '<path d="M10 20v-6h4v6"/>',
    "platform": '<path d="M5 10v4h3l7 4V6l-7 4Z"/>'
                '<path d="M18 9a4 4 0 0 1 0 6"/>',
    "linked": '<path d="m5 13 4 4 10-10"/>',
    "empty": '<circle cx="12" cy="12" r="7"/>',
}


def icon(name):
    return (f'<svg class="ico" viewBox="{BOX}" aria-hidden="true" fill="none" '
            f'stroke="currentColor" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICON.get(name) or ICON["empty"]}</svg>')
