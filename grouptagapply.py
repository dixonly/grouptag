#!/usr/bin/env python3
import sys
import csv
import argparse
from nsxconnect import NsxConnect
import getpass
import ipaddress
import uuid
import copy
from datetime import datetime
import json
from logger import Logger

def parseParameters():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", required=True, help="JSON file")
    parser.add_argument("-n", "--nsx", required=True, help="NSX Manager")
    parser.add_argument("-u", "--user", required=False, default="admmin",
                        help="NSX user, defaults to admin")
    parser.add_argument("-p", "--password", required=False,
                        help="NSX user password")
    parser.add_argument("-l", "--logfile", required=False, default="logfile.txt")
    parser.add_argument("-g", "--globalmanager", required=False, action="store_true",
                         help="Sent group creation to global manager, --nsx must point to GM, works only with --mode=group")
    parser.add_argument("-m", "--mode", choices=["vm", "segment", "group", "all"], required=True,
                        help="vm: tag VMs, segment: tag segments, group: create all groups, all: apply groups, vm tags, segment tags")
    parser.add_argument("-r","--remove", action="store_true",
                        help="If specified, will delete the configurations pushed from input file")
    parser.add_argument("--rfilter", required=False,
                        help="If -r is specified, file containing list of --vms tags, --segment tags, or groups to removed")
    parser.add_argument("--trial", action="store_true",
                        help="If specified, will not send updates to NSX, just print")

    args = parser.parse_args()
    if args.globalmanager and args.mode != "group":
        sys.stderr.write("Specified --globalmanager but --mode is not group")
        exit()
    return args

def filterObject(obj, rfilter):
    if not rfilter:
        return False
    if obj["display_name"] in rfilter:
        return True
    else:
        return False
        

def applyGroup(nsx, groups, remove, rfilter, trial=False):
    for group in groups:
        if not remove:
            if group["method"] == "patch":
                nsx.patch(api=group["url"], data=group["payload"],
                          verbose=True, codes=[200], trial=trial)
        else:
            action = True
            if rfilter and group["display_name"] in rfilter:
                action=True
            else:
                action=False
            if action:
                nsx.delete(api=group["url"], verbose=True, codes=[200, 201], trial=trial)    

def applySegmentTags(nsx, segments, remove, rfilter, trial=False):
    for segment in segments:
        if not remove:
            if segment["method"] == "patch":
                nsx.patch(api=segment["url"], data=segment["payload"],
                          verbose=True, codes=[200], trial=trial)
        else:
            action = True
            if rfilter and segment["display_name"] in rfilter:
                action=True
            else:
                action=False
                
            if segment["method"] == "patch":
                segment["payload"]["tags"] = segment["original_tags"]
                nsx.patch(api=segment["url"], data=segment["payload"],
                          verbose=True, codes=[200], trial=trial)
            

def applyVMTags(nsx, scopes, remove, rfilter, allvmnames, allvmids, pagesize=1000, trial=False):
    for scope in scopes:
        if not remove:
            for tag in scope["tags"]:
                cursor = 0
                vmlist = tag["apply_to"][0]["resource_ids"]
                
                while(cursor < len(vmlist)):
                    tag["apply_to"][0]["resource_ids"] = vmlist[cursor:cursor+pagesize]
                    api="/policy/api/v1/infra/tags/tag-operations/vm_tag_op_%s" % uuid.uuid4()
                    nsx.put(api=api, data=tag, verbose=True, codes=[200], trial=trial)
                    cursor+=pagesize
        else:
            for tag in scope["tagsremove"]:
                cursor = 0
                vmlist = tag["remove_from"][0]["resource_ids"]
                while(cursor < len(vmlist)):
                    if not rfilter:
                        tag["remove_from"][0]["resource_ids"] = vmlist[cursor:cursor+pagesize]
                    else:
                        tag["remove_from"][0]["resource_ids"] = []
                        for n in rfilter:
                            if n in allvmnames:
                                tag["remove_from"][0]["resource_ids"].append(allids[allvmnames.index(n)])
                    api="/policy/api/v1/infra/tags/tag-operations/vm_tag_op_%s" % uuid.uuid4()
                    nsx.put(api=api, data=tag, verbose=True, codes=[200], trial=trial)
                    cursor+=pagesize

                
def main():
    args = parseParameters()
    logger = Logger(args.logfile)
    if not args.password:
        args.password = getpass.getpass("NSX Manager %s password: " %args.nsx)
    with open(args.input, 'r', newline='') as fp:
        data = json.load(fp)
        fp.close()

    if not args.globalmanager:
        nsx = NsxConnect(server=args.nsx, logger=logger, 
                         user=args.user, password=args.password)
    else:
        nsx = NsxConnect(server=args.nsx, logger=logger, global_infra=True, global_gm=True,
                         user=args.user, password=args.password)

    if args.remove and args.rfilter:
        with open(args.rfilter, 'r') as fp:
            csvreader = csv.reader(fp)
            rcsv = [row for row in csvreader]
            rfilter=[]
            for row in rcsv:
                rfilter.append(row[0])
            fp.close()
            allvmms = nsx.get(api="/policy/api/v1/infra/realized-state/virtual-machines",
                              code=[200], verbose=False, display=False)
            allvmnames=[v["display_name"] for v in allvms]
            allvmids = [v["external_id"] for v in allvms]
    else:
        rfilter=None
        allvmnames=[]
        allvmids=[]


    if args.mode == "group":
        applyGroup(nsx, data["groups"], args.remove, rfilter, trial=args.trial)
    elif args.mode == "vm":
        applyVMTags(nsx, data["scopes"], args.remove, rfilter, allvmnames, allvmids, trial=args.trial)
    elif args.mode == "segment":
        applySegmentTags(nsx, data["segments"], args.remove, rfilter, trial=args.trial)
    elif args.mode == 'all':
        applyGroup(nsx, data["groups"], args.remove, rfilter, trial=args.trial)
        applyVMTags(nsx, data["scopes"], args.remove, rfilter, allvmnames, allvmids, trial=args.trial)
        applySegmentTags(nsx, data["segments"], args.remove, rfilter, trial=args.trial)

    
    
    
if __name__ == "__main__":
    main()
