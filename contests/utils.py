WIKIMEDIA_API_HEADERS = {
    "User-Agent": "WikiScore/1.0 (https://github.com/WikiMovimentoBrasil/wikiscore; wikiscore@wmnobrasil.org)"
}

def flatten_statements(entity):
    """Returns a statement dictionary {statement_id: statement} from a Wikidata entity JSON """
    statements = {}
    for claims in entity.get('claims', {}).values():
        for claim in claims:
            statements[claim['id']] = claim
    return statements


def flatten_snaks_by_property(snaks_dict):
    """ Returns a dictionary {property_id: set(hashs)} based on qualifiers or references """
    by_property = {}
    for properties, snaks in snaks_dict.items():
        for snak in snaks:
            if 'hash' in snak:
                by_property.setdefault(properties, set()).add(snak['hash'])
    return by_property



def diff_snaks(before_snaks_dict, after_snaks_dict):
        """Returns snaks created and modified comparing by property and not by hash """
        before_by_property = flatten_snaks_by_property(before_snaks_dict)
        after_by_property = flatten_snaks_by_property(after_snaks_dict)

        created = 0
        modified = 0

        for properties, after_hashes in after_by_property.items():
            if properties not in before_by_property:
                created += len(after_hashes)
            else:
                new_hashes = after_hashes - before_by_property[properties]
                if new_hashes:
                    modified += len(new_hashes)
        return created, modified