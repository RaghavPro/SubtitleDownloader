from os import path

import os
import sys
import struct
import xmlrpclib
import gzip
import base64
import collections


server_url = 'http://api.opensubtitles.org/xml-rpc';
user_agent = 'OSTestUserAgent'

class OpenSubtitlesAPI:

    server = None

    def createSubFile(self, gzipSub, subFilePath):
        with open(subFilePath, 'wb') as subFile:
            subFile.write(gzipSub)

        with gzip.open(subFilePath, 'rb') as subFile:
            decodedSub = subFile.read()

        with open(subFilePath, 'wb') as subFile:
            subFile.write(decodedSub)


    def decodeSub(self, encodedSub):
        decoded_sub = base64.b64decode(encodedSub)
        return decoded_sub

    def downloadEncodedSub(self, token, subId):
        result = self.server.DownloadSubtitles(token, [subId])
        if result['status'] == "200 OK":
            data = result['data']
            if data != False:
                encodedSub = data[0]['data']
            else:
                print "Cannot find subtitle for this file."
                return None
        else:
            print "No response from server, try later."
            return None
        return encodedSub

    # This is our custom rating algorithm, to find the best suitable sub in a list of dictionaries.
    # It inserts our calulated rating value in the dictionary and returns the list.
    def ratingAlgorithm(self, data):
        for i in data:
            i['ratingAlgo'] = 0
            if int(i['SubBad']) > 0:
                i['ratingAlgo'] -= 5
            rating = float(i['SubRating'])
            if rating < 4.0 and rating > 0.0:
                i['ratingAlgo'] -= 5
            else:
                i['ratingAlgo'] += round(rating)
            if i['UserRank'] == "administrator" or i['UserRank'] == "trusted":
                i['ratingAlgo'] += 1
        return data

    # OpenSubtitles DB is fucked up, it returns multiple results and sometimes of different movies/series
    # So we have to do a lot of shit to find the best sub.
    def searchSub(self, token, data):
        result = self.server.SearchSubtitles(token, data)
        if result['status'] == "200 OK":
            data = result['data']
            if data != False:

                # Gets the two most common movie from result by matching imdb ids
                # (Like is said, sometimes there can be different movies in result, so we use the most common
                # movie in the result (by checking their IMDBids) and use that. We get the 2nd most common to
                # check if the count of 1 & 2 are not equal, in that case we use the original result.
                most_common_movie = collections.Counter(i['IDMovieImdb'] for i in data).most_common(2)
                movieCount = len(most_common_movie)

                # We choose the most common movie if the count of 1st & 2nd are different.
                # [0][0] is IMDb id and [0][1] is count of those IMDb ids in result
                isMostCommon = (movieCount > 1 and most_common_movie[0][1] != most_common_movie[1][1]) or movieCount == 1
                if isMostCommon:
                    data = [i for i in data if i['IDMovieImdb'] == most_common_movie[0][0]]

                data = self.ratingAlgorithm(data)

                # We sort the data on the basis of our rating algorithm and sub add date(Assuming latest sub would be better)
                sortedData = sorted(data, key=lambda k: (float(k['ratingAlgo']), k['SubAddDate']), reverse=True)

                # We get the top most result
                result = sortedData[0]

                # No need to change the sub name to actual movie name if we're not sure the movie is correct or not
                if isMostCommon:
                    if result['MovieKind'] == "episode":
                        fileName = "[S%02dE%02d] %s" % (int(result['SeriesSeason']), int(result['SeriesEpisode']), str(result['MovieName']).replace('" ', ' - ').replace('"', ''))
                    else:
                        fileName = "[%s] %s" % (result['MovieYear'], result['MovieName'])
                else:
                    fileName = None
                result['customName'] = fileName

                return result
            else:
                print "Couldn't find subtitle for this file."
                return None
        else:
            print "No response from server, try later."
            return None

    def hashFile(self, name):
        try:
            longlongformat = '<q'  # little-endian long long
            bytesize = struct.calcsize(longlongformat)

            f = open(name, "rb")

            filesize = path.getsize(name)
            hash = filesize

            if filesize < 65536 * 2:
                return "SizeError"

            for x in range(65536/bytesize):
                buffer = f.read(bytesize)
                (l_value,)= struct.unpack(longlongformat, buffer)
                hash += l_value
                hash = hash & 0xFFFFFFFFFFFFFFFF #to remain as 64bit number


            f.seek(max(0,filesize-65536),0)
            for x in range(65536/bytesize):
                buffer = f.read(bytesize)
                (l_value,)= struct.unpack(longlongformat, buffer)
                hash += l_value
                hash = hash & 0xFFFFFFFFFFFFFFFF

            f.close()
            returnedhash =  "%016x" % hash
            return returnedhash, filesize
        except(IOError):
              return "IOError"

    def login(self, lang, username="", password=""):
        try:
            result = self.server.LogIn(username, password, lang, user_agent)
            return result
        except Exception, e:
            print 'An error occured while logging in: %s' % e
            sys.exit(1)

    def init(self, filesData, lang):
        self.server = xmlrpclib.Server(server_url);

        loginData = self.login(lang)

        if loginData['status'] == "200 OK":
            token = loginData['token']
            for i,fileData in enumerate(filesData):
                file = path.join(fileData[0], fileData[1] + fileData[2])
                _hash, fileSize = self.hashFile(file)

                if _hash == "SizeError" or _hash == "IOError":
                    print "Uh-oh, a " + _hash + " occured. Make sure your file is greater than 132kb"
                    continue

                searchData = [{'moviehash' : _hash, 'moviebytesize' : fileSize, 'sublanguageid' : lang}]
                result = self.searchSub(token, searchData)

                if result is None:
                    filesData.pop(i)
                    continue

                subId = result['IDSubtitleFile']
                encodedSub = self.downloadEncodedSub(token, subId)

                if encodedSub is None: #This would never happen but meh...
                    filesData.pop(i)
                    continue

                gzipSub = self.decodeSub(encodedSub)

                subFileName = newMovieName = result['customName'] = fileData[1] if result['customName'] is None else result['customName']
                subFile = path.join(fileData[0], subFileName + "." + result['SubFormat'])
                self.createSubFile(gzipSub, subFile)

                newMovieFilePath = path.join(fileData[0], newMovieName + fileData[2])
                os.rename(file, newMovieFilePath)


videoExts =".avi.mp4.mkv.mpeg.flv.3gp2.3gp.3gp2.3gpp.60d.ajp.asf.asx.avchd.bik.mpe.bix\
            .box.cam.dat.divx.dmf.dv.dvr-ms.evo.flc.fli.flic.flx.gvi.gvp.h264.m1v.m2p\
            .m2ts.m2v.m4e.m4v.mjp.mjpeg.mjpg.mpg.moov.mov.movhd.movie.movx.wx.mpv\
            .mpv2.mxf.nsv.nut.ogg.ogm.omf.ps.qt.ram.rm.rmvb.swf.ts.vfw.vid.video.viv\
            .vivo.vob.vro.wm.wmv.wmx.wrap.wvx.x264.xvid"

def main():
    if len(sys.argv) == 1:
        print("Specify the path to the directory or file.")
        sys.exit(1)

    directory = sys.argv[1]

    filesData = []
    for fileName in os.listdir(directory):
        file = path.join(directory, fileName)
        if path.isfile(file):
            ext = path.splitext(file)[1]
            if ext == "": #Getting .DS_STORE on mac
                continue
            if ext in videoExts:
                filesData.append([directory, fileName.replace(ext, ""), ext])
    o = OpenSubtitlesAPI()
    o.init(filesData, 'eng')

if __name__ == '__main__':
    main()
