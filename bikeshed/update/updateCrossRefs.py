# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals
import io
import json
import re
import urllib2
from collections import defaultdict
from contextlib import closing

from .. import config
from ..apiclient.apiclient import apiclient
from ..messages import *



def update():
    try:
        say("Downloading anchor data...")
        shepherd = apiclient.APIClient("https://api.csswg.org/shepherd/", version="vnd.csswg.shepherd.v1")
        res = shepherd.get("specifications", anchors=True, draft=True)
        # http://api.csswg.org/shepherd/spec/?spec=css-flexbox-1&anchors&draft, for manual looking
        if ((not res) or (406 == res.status)):
            die("Either this version of the anchor-data API is no longer supported, or (more likely) there was a transient network error. Try again in a little while, and/or update Bikeshed. If the error persists, please report it on GitHub.")
            return
        if res.contentType not in config.anchorDataContentTypes:
            die("Unrecognized anchor-data content-type '{0}'.", res.contentType)
            return
        rawSpecData = res.data
    except Exception, e:
        die("Couldn't download anchor data.  Error was:\n{0}", str(e))
        return

    def linearizeAnchorTree(multiTree, list=None):
        if list is None:
            list = []
        # Call with multiTree being a list of trees
        for item in multiTree:
            if item['type'] in config.dfnTypes.union(["dfn", "heading"]):
                list.append(item)
            if item.get('children'):
                linearizeAnchorTree(item['children'], list)
                del item['children']
        return list

    specs = dict()
    anchors = defaultdict(list)
    headings = defaultdict(dict)
    for rawSpec in rawSpecData.values():
        spec = {
            'vshortname': rawSpec['name'],
            'shortname': rawSpec.get('short_name'),
            'snapshot_url': rawSpec.get('base_uri'),
            'current_url': rawSpec.get('draft_uri'),
            'title': rawSpec.get('title'),
            'description': rawSpec.get('description'),
            'work_status': rawSpec.get('work_status'),
            'working_group': rawSpec.get('working_group'),
            'domain': rawSpec.get('domain'),
            'status': rawSpec.get('status'),
            'abstract': rawSpec.get('abstract')
        }
        if spec['shortname'] is not None and spec['vshortname'].startswith(spec['shortname']):
            # S = "foo", V = "foo-3"
            # Strip the prefix
            level = spec['vshortname'][len(spec['shortname']):]
            if level.startswith("-"):
                level = level[1:]
            if level.isdigit():
                spec['level'] = int(level)
            else:
                spec['level'] = 1
        elif spec['shortname'] is None and re.match(r"(.*)-(\d+)", spec['vshortname']):
            # S = None, V = "foo-3"
            match = re.match(r"(.*)-(\d+)", spec['vshortname'])
            spec['shortname'] = match.group(1)
            spec['level'] = int(match.group(2))
        else:
            spec['shortname'] = spec['vshortname']
            spec['level'] = 1
        specs[spec['vshortname']] = spec
        specHeadings = headings[spec['vshortname']]

        def setStatus(status):
            def temp(obj):
                obj['status'] = status
                return obj
            return temp
        rawAnchorData = map(setStatus('snapshot'), linearizeAnchorTree(rawSpec.get('anchors', []))) + map(setStatus('current'), linearizeAnchorTree(rawSpec.get('draft_anchors',[])))
        for rawAnchor in rawAnchorData:
            rawAnchor = fixupAnchor(rawAnchor)
            linkingTexts = rawAnchor.get('linking_text', [rawAnchor.get('title')])
            if linkingTexts[0] is None:
                continue
            if len(linkingTexts) == 1 and linkingTexts[0].strip() == "":
                continue
            # If any smart quotes crept in, replace them with ASCII.
            for i,t in enumerate(linkingTexts):
                if "’" in t or "‘" in t:
                    t = re.sub(r"‘|’", "'", t)
                    linkingTexts[i] = t
                if "“" in t or "”" in t:
                    t = re.sub(r"“|”", '"', t)
                    linkingTexts[i] = t
            if rawAnchor['type'] == "heading":
                uri = rawAnchor['uri']
                if uri.startswith("??"):
                    # css3-tables has this a bunch, for some strange reason
                    uri = uri[2:]
                if uri[0] == "#":
                    # Either single-page spec, or link on the top page of a multi-page spec
                    heading = {
                        'url': spec["{0}_url".format(rawAnchor['status'])] + uri,
                        'number': rawAnchor['name'] if re.match(r"[\d.]+$", rawAnchor['name']) else "",
                        'text': rawAnchor['title'],
                        'spec': spec['title']
                    }
                    fragment = uri
                    shorthand = "/" + fragment
                else:
                    # Multi-page spec, need to guard against colliding IDs
                    if "#" in uri:
                        # url to a heading in the page, like "foo.html#bar"
                        match = re.match(r"([\w-]+).*?(#.*)", uri)
                        if not match:
                            die("Unexpected URI pattern '{0}' for spec '{1}'. Please report this to the Bikeshed maintainer.", uri, spec['vshortname'])
                            continue
                        page, fragment = match.groups()
                        page = "/" + page
                    else:
                        # url to a page itself, like "foo.html"
                        page, _, _ = uri.partition(".")
                        page = "/" + page
                        fragment = "#"
                    shorthand = page + fragment
                    heading = {
                        'url': spec["{0}_url".format(rawAnchor['status'])] + uri,
                        'number': rawAnchor['name'] if re.match(r"[\d.]+$", rawAnchor['name']) else "",
                        'text': rawAnchor['title'],
                        'spec': spec['title']
                    }
                if shorthand not in specHeadings:
                    specHeadings[shorthand] = {}
                specHeadings[shorthand][rawAnchor['status']] = heading
                if fragment not in specHeadings:
                    specHeadings[fragment] = []
                if shorthand not in specHeadings[fragment]:
                    specHeadings[fragment].append(shorthand)
            else:
                anchor = {
                    'status': rawAnchor['status'],
                    'type': rawAnchor['type'],
                    'spec': spec['vshortname'],
                    'shortname': spec['shortname'],
                    'level': int(spec['level']),
                    'export': rawAnchor.get('export', False),
                    'normative': rawAnchor.get('normative', False),
                    'url': spec["{0}_url".format(rawAnchor['status'])] + rawAnchor['uri'],
                    'for': rawAnchor.get('for', [])
                }
                for text in linkingTexts:
                    if anchor['type'] in config.lowercaseTypes:
                        text = text.lower()
                    text = re.sub(r'\s+', ' ', text)
                    anchors[text].append(anchor)

    # Headings data was purposely verbose, assuming collisions even when there wasn't one.
    # Want to keep the collision data for multi-page, so I can tell when you request a non-existent page,
    # but need to collapse away the collision stuff for single-page.
    for specHeadings in headings.values():
        for k, v in specHeadings.items():
            if k[0] == "#" and len(v) == 1 and v[0][0:2] == "/#":
                # No collision, and this is either a single-page spec or a non-colliding front-page link
                # Go ahead and collapse them.
                specHeadings[k] = specHeadings[v[0]]
                del specHeadings[v[0]]

    # Compile a db of {argless methods => {argfull method => {args, fors, url, shortname}}
    methods = defaultdict(dict)
    for key, anchors_ in anchors.items():
        # Extract the name and arguments
        match = re.match(r"([^(]+)\((.*)\)", key)
        if not match:
            continue
        methodName, argstring = match.groups()
        arglessMethod = methodName + "()"
        args = [x.strip() for x in argstring.split(",")] if argstring else []
        for anchor in anchors_:
            if anchor['type'] not in config.idlMethodTypes:
                continue
            if key not in methods[arglessMethod]:
                methods[arglessMethod][key] = {"args":args, "for": set(), "shortname":anchor['shortname']}
            methods[arglessMethod][key]["for"].update(anchor["for"])
    # Translate the "for" set back to a list for JSONing
    for signatures in methods.values():
        for signature in signatures.values():
            signature["for"] = list(signature["for"])

    # Compile a db of {for value => dict terms that use that for value}
    fors = defaultdict(set)
    for key, anchors_ in anchors.items():
        for anchor in anchors_:
            for for_ in anchor["for"]:
                if for_ == "":
                    continue
                fors[for_].add(key)
            if not anchor["for"]:
                fors["/"].add(key)
    for key, val in fors.items():
        fors[key] = list(val)

    if not config.dryRun:
        try:
            with io.open(config.scriptPath + "/spec-data/specs.json", 'w', encoding="utf-8") as f:
                f.write(unicode(json.dumps(specs, ensure_ascii=False, indent=2, sort_keys=True)))
        except Exception, e:
            die("Couldn't save spec database to disk.\n{0}", e)
            return
        try:
            with io.open(config.scriptPath + "/spec-data/headings.json", 'w', encoding="utf-8") as f:
                f.write(unicode(json.dumps(headings, ensure_ascii=False, indent=2, sort_keys=True)))
        except Exception, e:
            die("Couldn't save headings database to disk.\n{0}", e)
            return
        try:
            with io.open(config.scriptPath + "/spec-data/anchors.data", 'w', encoding="utf-8") as f:
                writeAnchorsFile(f, anchors)
        except Exception, e:
            die("Couldn't save anchor database to disk.\n{0}", e)
            return
        try:
            with io.open(config.scriptPath + "/spec-data/methods.json", 'w', encoding="utf-8") as f:
                f.write(unicode(json.dumps(methods, ensure_ascii=False, indent=2, sort_keys=True)))
        except Exception, e:
            die("Couldn't save methods database to disk.\n{0}", e)
            return
        try:
            with io.open(config.scriptPath + "/spec-data/fors.json", 'w', encoding="utf-8") as f:
                f.write(unicode(json.dumps(fors, ensure_ascii=False, indent=2, sort_keys=True)))
        except Exception, e:
            die("Couldn't save fors database to disk.\n{0}", e)
            return

    say("Success!")


def fixupAnchor(anchor):
    # Miscellaneous fixes
    if anchor.get('title', None) == "'@import'":
        anchor['title'] = "@import"
    for k,v in anchor.items():
        # Normalize whitespace
        if isinstance(v, basestring):
            anchor[k] = re.sub(r"\s+", " ", v.strip())
        elif isinstance(v, list):
            for k1, v1 in enumerate(v):
                if isinstance(v1, basestring):
                    anchor[k][k1] = re.sub(r"\s+", " ", v1.strip())
    return anchor


def writeAnchorsFile(fh, anchors):
    '''
    Keys may be duplicated.

    key
    type
    spec
    shortname
    level
    status
    url
    export (boolish string)
    normative (boolish string)
    for* (one per line, unknown #)
    - (by itself, ends the segment)
    '''
    for key, entries in anchors.items():
        for e in entries:
            fh.write(key + "\n")
            for field in ["type", "spec", "shortname", "level", "status", "url"]:
                fh.write(unicode(e.get(field, "")) + "\n")
            for field in ["export", "normative"]:
                if e.get(field, False):
                    fh.write("1\n")
                else:
                    fh.write("\n")
            for forValue in e.get("for", []):
                if forValue:  # skip empty strings
                    fh.write(forValue + "\n")
            fh.write("-" + "\n")