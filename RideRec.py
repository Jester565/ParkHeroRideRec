import Accel_pb2
import matplotlib.pyplot as plt
from matplotlib.widgets import SpanSelector
import math
import os.path
from functools import partial

RecSections = []
MAX_DIST = 10
MAX_POINT_DIFF = 20
ACCEL_STEP = 1

#Gets array of indices where the value in the array changed
# ex. [ 0, 0, 0, 1, 1, 0, 0, 0, 0] array to [ 3, 5 ]
def getArrTransitions(smartAvgs):
    transitions = []
    lastVal = 0
    for idx, val in enumerate(smartAvgs):
        if val != lastVal:
            transitions.append(idx)
            lastVal = val
    return transitions

#Converts accelerations into 1d array with 0 values for no noteable acceleration and 1 for significant acceleration (intended to filter out inaccurate data and simplify matching)
# millisArr: Array of the time the values with the corresponding index in accelArrs were taken (millis starts at 0)
# accelArrs: 2D array, each acceleration axis (x, y, z) has an array of acceleration magnitude (from 10,000 to -10,000)
# millisWindowSize: For each millisWindowSize / 2 interval, get moving average of acceleration and # of sign changes that occured
# signChangeLimit: If the any acceleration axis experienced x sign changes within a window, set to 0
# accelThreshold: Magnitude of average acceleration must be greater than the threshold to be added
def smartAverage(millisArr, accelArrs, millisWindowSize, signChangeLimit, accelThreshold):
    window = []
    signChangeWindow = []
    #Init values in window
    for idx, val in enumerate(accelArrs):
        window.append(0)
        signChangeWindow.append(0)

    smartAvgs = []
    #index at beginning of window
    startI = 0
    #index at end of window
    endI = 0
    currentMillis = millisArr[0]
    #In each iteration, the window moves
    while True:
        currentMillis += millisWindowSize / 2
        #move starting index up until the window is reached, Remove acceleration magnitudes and sign changes from window as we shift it
        while (millisArr[startI] < currentMillis - millisWindowSize / 2):
            for idx, arr in enumerate(accelArrs):
                window[idx] -= arr[startI]
                if startI > 0 and arr[startI] * arr[startI - 1] < 0:
                    signChangeWindow[idx] -= 1
            startI += 1
        #move ending index up, Add acceleration magnitudes and sign changes to the window
        while (millisArr[endI] < currentMillis + millisWindowSize / 2):
            for idx, arr in enumerate(accelArrs):
                window[idx] += arr[endI]
                if endI > 0 and arr[endI] * arr[endI - 1] < 0:
                    signChangeWindow[idx] += 1
            endI += 1
            if (endI >= len(millisArr)):
                return smartAvgs
        avgSum = 0
        #Get average magnitude
        for idx, val in enumerate(window):
            val = val / (endI - startI + 1)
            if signChangeWindow[idx] <= signChangeLimit:
                avgSum += val * val
        if math.sqrt(avgSum) >= accelThreshold:
            smartAvgs.append(1)
        else:
            smartAvgs.append(0)

#Callback when user highlights a section of the acceleration graph
# smartAvgs: The smartAvg (array of 0 and 1)
def onRecSectionAdded(smartAvgs, xMin, xMax):
    name = input("Enter RecSection Name: ")
    recSectionSmartAvgs = smartAvgs[int(xMin):int(xMax)]
    #Each recSection (recognitionSection) gets its own name so it can later be assigned to video
    recSection = {
          "name": name,
          "smartAvgs": recSectionSmartAvgs,
          "xMin": int(xMin),
          "xMax": int(xMax)
    }
    RecSections.append(recSection)

#Create a recognition pack (which consists of recSections [or points in the .proto])
def packify(packName, recSections):
    #Remove existing pack from proto containing all recognitionPacks
    ridePacks = Accel_pb2.RidePacks()
    if os.path.isfile('packs'):
        packFile = open('packs', 'rb')
        raw = packFile.read()
        ridePacks.ParseFromString(raw)
        for packIdx, rp in enumerate(ridePacks.packs):
            if (rp.name == packName):
                del ridePacks.packs[packIdx]
        packFile.close()

    #Create recognition pack and add it to packs
    ridePack = ridePacks.packs.add()
    lastXMax = -1
    for recSection in recSections:
        point = ridePack.points.add()
        point.name = recSection["name"]
        point.transitions.extend(getArrTransitions(recSection["smartAvgs"]))
        point.duration = int(recSection["xMax"] - recSection["xMin"])
        if lastXMax > 0:
            point.dist = int(recSection["xMin"] - lastXMax)
        lastXMax = recSection["xMax"]
    ridePack.name = packName
    ridePack.duration = int(recSections[len(recSections) - 1]["xMax"] - recSections[0]["xMin"])

    print("RidePack Contains")
    for rp in ridePacks.packs:
        print(rp.name)
    packFileWrite = open('packs', 'wb')
    packFileWrite.write(ridePacks.SerializeToString())
    packFileWrite.close()

#Find the points in the recogntionPack where the times are the closest
# accels: The smartAverage we're trying to recognize
# accelStartI: Index to start recognition
# maxAccelI: Index to end recognition
# recSections: Remaining RecSections that we're attempting to match
# accelStep: Matches will only be accurate within the milliseconds of the accelStep
# distMap: Memoization prevents recalculating distances
def getMinAccel(accels, accelStartI, maxAccelI, recSections, accelStep, distMap):
    #transitionI vs accelerationI
    # accelerationI represents the index of the smartAverage points
    # the transition array (accels) has VALUES that are an INDEX to the smartAverage
    minDist = None
    minMatches = None
    #The index we will test the distance of
    targetAccelI = accelStartI
    transitionI = 0
    while True:
        if targetAccelI > maxAccelI:
            break
        #Find closest subsequent transition to the time
        while True:
            if transitionI >= len(accels) or accels[transitionI] >= targetAccelI:
                break
            transitionI += 1
        distance = 0
        #Each match is the accelerationI where the recSection began, the # of matches should = the # of recSections
        matches = [targetAccelI]
        distKey = recSections[0].name + str(targetAccelI)
        #Make sure we are not redoing a calculation
        if distKey not in distMap:
            #Get distance of recSection from the acceleration we were given
            distance = getAccelsDistanceFromRecSection(accels, recSections[0].transitions, targetAccelI, transitionI)
            #If there are more recSections, find their best distance after this point
            if len(recSections) > 1:
                minDistResult = getMinAccel(accels, targetAccelI + recSections[0].duration + recSections[1].dist - MAX_POINT_DIFF, targetAccelI + recSections[0].duration + recSections[1].dist + MAX_POINT_DIFF, recSections[1:], accelStep, distMap)
                distance += minDistResult["distance"]
                matches += minDistResult["matches"]
            #Save to distMap to reuse calculations
            distMap[distKey] = { 
                "distance": distance, 
                "matches": matches
            }
        else:
            minDistResult = distMap[distKey]
            distance = minDistResult["distance"]
            matches = minDistResult["matches"]
        if minDist is None or distance < minDist:
            minDist = distance
            minMatches = matches
        #Move accelI to next target
        targetAccelI += accelStep
    return {
        "distance": minDist,
        "matches": minMatches
    }

#Determine distance of acceleration arrays
# accels: A transition array of the acceleration we're recognizing
# rideAccels: A transition array of the acceleration we're comparing against
# accelStartI: The accelerationI we're starting at
def getAccelsDistanceFromRecSection(accels, rideAccels, accelStartI, transitionStartI):
    accelI = 0
    rideI = 0
    distance = 0
    lastDistHigh = False
    while True:
        initialRideI = rideI
        #Run through ride points if accel array has ended or 
        while rideI < len(rideAccels) and (accelI + transitionStartI >= len(accels) or rideAccels[rideI] < accels[accelI + transitionStartI] - accelStartI):
            distanceResult = getArrDistance(accels, rideAccels, accelI + transitionStartI, rideI, accelStartI, 0)
            lastDistHigh = distanceResult["high"]
            distance += distanceResult["distance"]
            rideI += 1
        if rideI >= len(rideAccels):
            break
        distanceResult = getArrDistance(rideAccels, accels, rideI, accelI + transitionStartI, 0, accelStartI)
        lastDistHigh = distanceResult["high"]
        distance += distanceResult["distance"]
        accelI += 1
    return distance

def getArrDistance(bigArr, subArr, highI, midI, bigOff = 0, subOff = 0, blockLow = False, blockHigh = False):
    lowDist = MAX_DIST
    highDist = MAX_DIST
    if highI > 0 and highI <= len(bigArr) and midI < len(subArr):
        lowDist = (subArr[midI] - subOff) - (bigArr[highI - 1] - bigOff)
    if highI >= 0 and highI < len(bigArr) and midI < len(subArr):
        highDist = (bigArr[highI] - bigOff) - (subArr[midI] - subOff)
    minDist = 0
    if not blockLow and not blockHigh:
        minDist = min(lowDist, highDist)
    elif not blockLow:
        minDist = lowDist
    elif not blockHigh:
        minDist = highDist
    return {
        "high": minDist == highDist,
        "distance": calcDistance(minDist)
    }

def calcDistance(dist):
    if dist < MAX_DIST:
        return dist
    else:
        return MAX_DIST

#Invoked whenever section of graph is highlighted for recognition
def onRecognize(smartAverages, xMin, xMax):
    smartAvgs = smartAverages[int(xMin):int(xMax)]
    #Convert to transitionArray
    accels = getArrTransitions(smartAvgs)
    ridePacks = Accel_pb2.RidePacks()
    packFile = open('packs', 'rb')
    raw = packFile.read()
    ridePacks.ParseFromString(raw)
    minDist = None
    minName = None
    minMatches = None
    packs = []
    #Map of 
    distMap = {}
    #Find lowest (best match) for the portion of acceleration in the packs
    for packIdx, rp in enumerate(ridePacks.packs):
        accelResult = getMinAccel(accels, 0, len(smartAvgs) - rp.duration, rp.points, ACCEL_STEP, distMap)
        if minDist is None or accelResult["distance"] < minDist:
            minDist = accelResult["distance"]
            minName = rp.name
            minMatches = accelResult["matches"]
    packFile.close()
    modMinMatches = []
    for minMatch in minMatches:
        modMinMatches.append(int(minMatch + xMin))
    print("REC: ", minName, " -- ", minDist, " -- ", modMinMatches)

def main():
    #Fingerprint will create a RideRec Pack using GUI
    #Recognize will try to match the highlighted acceleration
    mode = input("Enter mode (fingerprint: f, recognize: r)")
    while True:
        accelFileName = input("Enter accelfile: ")
        if not os.path.isfile(accelFileName):
            print("File does not exist!")
            return
        with open(accelFileName, 'rb') as accelFile:
            raw = accelFile.read()
            accelData = Accel_pb2.AccelerationData()
            accelData.ParseFromString(raw)
            smartAvgs = smartAverage(accelData.millis, [accelData.x, accelData.y, accelData.z], 800, 3, 10000)
            smartAvgsMagnitude = []
            evenMillisArr = []
            for idx, val in enumerate(smartAvgs):
                evenMillisArr.append(idx)
            plt.title(accelFile)
            plt.legend(loc='upper left')
            fig, (ax1, ax2) = plt.subplots(2, 1)
            ax1.plot(evenMillisArr, smartAvgs, '-og', label='x')
            ax2.plot(accelData.millis, accelData.x)
            ax2.plot(accelData.millis, accelData.y)
            ax2.plot(accelData.millis, accelData.z)
            if mode == "f":
                span = SpanSelector(ax1, partial(onRecSectionAdded, smartAvgs), 'horizontal', useblit=True, rectprops=dict(alpha=0.5, facecolor='red'))
            else:
                span = SpanSelector(ax1, partial(onRecognize, smartAvgs), 'horizontal', useblit=True, rectprops=dict(alpha=0.5, facecolor='blue'))
            plt.show()
            if mode == "f":
                packName = input("Enter pack name: ")
                packify(packName, RecSections)
main()